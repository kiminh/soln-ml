import warnings
import numpy as np
from collections import Counter
from sklearn.preprocessing import OneHotEncoder
from torch.utils.data import DataLoader
from sklearn.metrics.scorer import _BaseScorer, _PredictScorer, _ThresholdScorer

from solnml.components.utils.constants import CLS_TASKS, TASK_TYPES, IMG_CLS
from solnml.datasets.base_dl_dataset import DLDataset
from solnml.components.ensemble.dl_ensemble.base_ensemble import BaseEnsembleModel
from solnml.components.evaluators.base_dl_evaluator import get_estimator_with_parameters
from solnml.components.models.img_classification.nn_utils.nn_aug.aug_hp_space import get_test_transforms


class EnsembleSelection(BaseEnsembleModel):
    def __init__(
            self, stats,
            ensemble_size: int,
            task_type: int,
            max_epoch: int,
            metric: _BaseScorer,
            timestamp: float,
            output_dir=None,
            device='cpu',
            sorted_initialization: bool = False,
            mode: str = 'fast',
            **kwargs
    ):
        super().__init__(stats=stats,
                         ensemble_method='ensemble_selection',
                         ensemble_size=ensemble_size,
                         task_type=task_type,
                         max_epoch=max_epoch,
                         metric=metric,
                         timestamp=timestamp,
                         output_dir=output_dir,
                         device=device)
        self.model_idx = list()
        self.sorted_initialization = sorted_initialization
        self.mode = mode
        self.encoder = OneHotEncoder()
        self.random_state = np.random.RandomState(self.seed)

        self.shape = None

        if self.task_type == IMG_CLS:
            self.image_size = kwargs['image_size']

    def calculate_score(self, pred, y_true):
        if isinstance(self.metric, _ThresholdScorer):
            if len(y_true.shape) == 1:
                y_true = self.encoder.transform(np.reshape(y_true, (len(y_true), 1))).toarray()
        elif self.task_type in CLS_TASKS and isinstance(self.metric, _PredictScorer):
            pred = np.argmax(pred, axis=-1)
        score = self.metric._score_func(y_true, pred) * self.metric._sign
        return score

    def fit(self, train_data):

        self.ensemble_size = int(self.ensemble_size)
        if self.ensemble_size < 1:
            raise ValueError('Ensemble size cannot be less than one!')
        if not self.task_type in TASK_TYPES:
            raise ValueError('Unknown task type %s.' % self.task_type)
        if not isinstance(self.metric, _BaseScorer):
            raise ValueError('Metric must be of type scorer')
        if self.mode not in ('fast', 'slow'):
            raise ValueError('Unknown mode %s' % self.mode)

        model_pred_list = list()
        num_samples = 0
        val_y = None

        for algo_id in self.stats["include_algorithms"]:
            model_configs = self.stats[algo_id]['model_configs']
            for idx, config in enumerate(model_configs):
                if self.task_type == IMG_CLS:
                    test_transforms = get_test_transforms(config, image_size=self.image_size)
                    train_data.load_data(test_transforms, test_transforms)
                else:
                    train_data.load_data()

                estimator = get_estimator_with_parameters(self.task_type, config, self.max_epoch,
                                                          train_data.train_dataset, self.timestamp, device=self.device)
                if self.task_type in CLS_TASKS:
                    if not train_data.subset_sampler_used:
                        pred = estimator.predict_proba(train_data.val_dataset)
                    else:
                        pred = estimator.predict_proba(train_data.train_for_val_dataset, sampler=train_data.val_sampler)
                else:
                    if not train_data.subset_sampler_used:
                        pred = estimator.predict(train_data.val_dataset)
                    else:
                        pred = estimator.predict(train_data.train_for_val_dataset, sampler=train_data.val_sampler)

                if not train_data.subset_sampler_used:
                    loader = DataLoader(train_data.val_dataset)
                else:
                    loader = DataLoader(train_data.train_for_val_dataset, sampler=train_data.val_sampler)

                if val_y is None:
                    val_y = list()
                    for sample in loader:
                        num_samples += 1
                        val_y.extend(sample[1].detach().numpy())
                    val_y = np.array(val_y)

                if len(val_y.shape) == 1 and self.task_type in CLS_TASKS:
                    reshape_y = np.reshape(val_y, (len(val_y), 1))
                    with warnings.catch_warnings():
                        warnings.filterwarnings("ignore", category=FutureWarning)
                        self.encoder.fit(reshape_y)

                if self.shape is None:
                    self.shape = pred.shape
                model_pred_list.append(pred)

        self._fit(model_pred_list, val_y)
        self._calculate_weights()
        self.identifiers_ = None

        model_cnt = 0
        for algo_id in self.stats["include_algorithms"]:
            model_configs = self.stats[algo_id]['model_configs']
            for _, _ in enumerate(model_configs):
                if self.weights_[model_cnt] != 0:
                    self.model_idx.append(model_cnt)
                model_cnt += 1

        return self

    def _fit(self, predictions, labels):
        if self.mode == 'fast':
            self._fast(predictions, labels)
        else:
            self._slow(predictions, labels)
        return self

    def _fast(self, predictions, labels):
        """Fast version of Rich Caruana's ensemble selection method."""
        self.num_input_models_ = len(predictions)

        ensemble = []
        trajectory = []
        order = []

        ensemble_size = self.ensemble_size

        if self.sorted_initialization:
            n_best = 20
            indices = self._sorted_initialization(predictions, labels, n_best)
            for idx in indices:
                ensemble.append(predictions[idx])
                order.append(idx)
                ensemble_ = np.array(ensemble).mean(axis=0)
                ensemble_performance = self.calculate_score(pred=ensemble_, y_true=labels)
                trajectory.append(ensemble_performance)
            ensemble_size -= n_best

        for i in range(ensemble_size):
            scores = np.zeros((len(predictions)))
            s = len(ensemble)
            if s == 0:
                weighted_ensemble_prediction = np.zeros(predictions[0].shape)
            else:
                # Memory-efficient averaging!
                ensemble_prediction = np.zeros(ensemble[0].shape)
                for pred in ensemble:
                    ensemble_prediction += pred
                ensemble_prediction /= s

                weighted_ensemble_prediction = (s / float(s + 1)) * \
                                               ensemble_prediction
            fant_ensemble_prediction = np.zeros(weighted_ensemble_prediction.shape)
            for j, pred in enumerate(predictions):
                # TODO: this could potentially be vectorized! - let's profile
                # the script first!
                if self.task_type in CLS_TASKS:
                    fant_ensemble_prediction[:, :] = weighted_ensemble_prediction + \
                                                     (1. / float(s + 1)) * pred
                else:
                    fant_ensemble_prediction[:] = weighted_ensemble_prediction + \
                                                  (1. / float(s + 1)) * pred

                scores[j] = -self.calculate_score(pred=fant_ensemble_prediction, y_true=labels)

            all_best = np.argwhere(scores == np.nanmin(scores)).flatten()
            best = self.random_state.choice(all_best)
            ensemble.append(predictions[best])
            trajectory.append(scores[best])
            order.append(best)

            # Handle special case
            if len(predictions) == 1:
                break

        self.indices_ = order
        self.trajectory_ = trajectory
        self.train_score_ = trajectory[-1]

    def _slow(self, predictions, labels):
        """Rich Caruana's ensemble selection method."""
        self.num_input_models_ = len(predictions)

        ensemble = []
        trajectory = []
        order = []

        ensemble_size = self.ensemble_size

        if self.sorted_initialization:
            n_best = 20
            indices = self._sorted_initialization(predictions, labels, n_best)
            for idx in indices:
                ensemble.append(predictions[idx])
                order.append(idx)
                ensemble_ = np.array(ensemble).mean(axis=0)
                ensemble_performance = self.calculate_score(pred=ensemble_, y_true=labels)
                trajectory.append(ensemble_performance)
            ensemble_size -= n_best

        for i in range(ensemble_size):
            scores = np.zeros([predictions.shape[0]])
            for j, pred in enumerate(predictions):
                ensemble.append(pred)
                ensemble_prediction = np.mean(np.array(ensemble), axis=0)
                scores[j] = -self.calculate_score(pred=ensemble_prediction, y_true=labels)
                ensemble.pop()
            best = np.nanargmin(scores)
            ensemble.append(predictions[best])
            trajectory.append(scores[best])
            order.append(best)

            # Handle special case
            if len(predictions) == 1:
                break

        self.indices_ = np.array(order)
        self.trajectory_ = np.array(trajectory)
        self.train_score_ = trajectory[-1]

    def _calculate_weights(self):
        ensemble_members = Counter(self.indices_).most_common()
        weights = np.zeros((self.num_input_models_,), dtype=float)
        for ensemble_member in ensemble_members:
            weight = float(ensemble_member[1]) / self.ensemble_size
            weights[ensemble_member[0]] = weight

        if np.sum(weights) < 1:
            weights = weights / np.sum(weights)

        self.weights_ = weights

    def _sorted_initialization(self, predictions, labels, n_best):
        perf = np.zeros([predictions.shape[0]])

        for idx, prediction in enumerate(predictions):
            perf[idx] = self.calculate_score(pred=predictions, y_true=labels)

        indices = np.argsort(perf)[perf.shape[0] - n_best:]
        return indices

    def predict(self, test_data: DLDataset, mode='test'):
        predictions = []
        cur_idx = 0
        num_samples = 0

        for algo_id in self.stats["include_algorithms"]:
            model_configs = self.stats[algo_id]['model_configs']
            for idx, config in enumerate(model_configs):
                if self.task_type == IMG_CLS:
                    test_transforms = get_test_transforms(config, image_size=self.image_size)
                    test_data.load_test_data(test_transforms)
                    test_data.load_data(test_transforms, test_transforms)
                else:
                    test_data.load_test_data()
                    test_data.load_data()

                if num_samples == 0:
                    if mode == 'test':
                        dataset = test_data.test_dataset
                        loader = DataLoader(dataset)
                        num_samples = len(loader)
                    else:
                        if test_data.subset_sampler_used:
                            dataset = test_data.train_dataset
                            num_samples = len(test_data.val_sampler)
                        else:
                            dataset = test_data.val_dataset
                            loader = DataLoader(dataset)
                            num_samples = len(loader)

                estimator = get_estimator_with_parameters(self.task_type, config, self.max_epoch,
                                                          dataset, self.timestamp, device=self.device)
                if cur_idx in self.model_idx:
                    if self.task_type in CLS_TASKS:
                        if mode == 'test':
                            predictions.append(estimator.predict_proba(test_data.test_dataset))
                        else:
                            if test_data.subset_sampler_used:
                                predictions.append(
                                    estimator.predict_proba(test_data.train_dataset, sampler=test_data.val_sampler))
                            else:
                                predictions.append(estimator.predict_proba(test_data.val_dataset))
                    else:
                        if mode == 'test':
                            predictions.append(estimator.predict(test_data.test_dataset))
                        else:
                            if test_data.subset_sampler_used:
                                predictions.append(
                                    estimator.predict(test_data.train_dataset, sampler=test_data.val_sampler))
                            else:
                                predictions.append(estimator.predict(test_data.val_dataset))
                else:
                    if len(self.shape) == 1:
                        predictions.append(np.zeros(num_samples))
                    else:
                        predictions.append(np.zeros((num_samples, self.shape[1])))
                cur_idx += 1

        predictions = np.asarray(predictions)

        # if predictions.shape[0] == len(self.weights_),
        # predictions include those of zero-weight models.
        if predictions.shape[0] == len(self.weights_):
            return np.average(predictions, axis=0, weights=self.weights_)

        # if prediction model.shape[0] == len(non_null_weights),
        # predictions do not include those of zero-weight models.
        elif predictions.shape[0] == np.count_nonzero(self.weights_):
            non_null_weights = [w for w in self.weights_ if w > 0]
            return np.average(predictions, axis=0, weights=non_null_weights)

        # If none of the above applies, then something must have gone wrong.
        else:
            raise ValueError("The dimensions of ensemble predictions"
                             " and ensemble weights do not match!")

    def __str__(self):
        return 'Ensemble Selection:\n\tTrajectory: %s\n\tMembers: %s' \
               '\n\tWeights: %s\n\tIdentifiers: %s' % \
               (' '.join(['%d: %5f' % (idx, performance)
                          for idx, performance in enumerate(self.trajectory_)]),
                self.indices_, self.weights_,
                ' '.join([str(identifier) for idx, identifier in
                          enumerate(self.identifiers_)
                          if self.weights_[idx] > 0]))

    def get_models_with_weights(self, models):
        output = []

        for i, weight in enumerate(self.weights_):
            identifier = self.identifiers_[i]
            model = models[identifier]
            if weight > 0.0:
                output.append((weight, model))

        output.sort(reverse=True, key=lambda t: t[0])

        return output

    def get_selected_model_identifiers(self):
        output = []

        for i, weight in enumerate(self.weights_):
            identifier = self.identifiers_[i]
            if weight > 0.0:
                output.append(identifier)

        return output

    def get_validation_performance(self):
        return self.trajectory_[-1]

    def get_ens_model_info(self):
        raise NotImplementedError
