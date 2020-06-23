import torch
import hashlib


def get_estimator(config, device='cpu'):
    from solnml.components.models.img_classification import _classifiers, _addons
    classifier_type = config['estimator']
    config_ = config.copy()
    config_.pop('estimator', None)
    config_['random_state'] = 1
    config_['device'] = device
    try:
        estimator = _classifiers[classifier_type](**config_)
    except:
        estimator = _addons.components[classifier_type](**config_)
    return classifier_type, estimator


def get_estimator_with_parameters(config, device='cpu', model_dir='data/dl_models/'):
    config_dict = config.get_dictionary().copy()
    _, model = get_estimator(config_dict, device=device)
    model_path = model_dir + TopKModelSaver.get_configuration_id(config_dict) + '.pt'
    model.model.load_state_dict(torch.load(model_path))
    model.model.eval()
    return model


class TopKModelSaver(object):
    def __init__(self, k, model_dir):
        self.k = k
        self.sorted_list = list()
        self.model_dir = model_dir

    @staticmethod
    def get_configuration_id(data_dict):
        data_list = []
        for key, value in sorted(data_dict.items(), key=lambda t: t[0]):
            if isinstance(value, float):
                value = round(value, 5)
            data_list.append('%s-%s' % (key, str(value)))
        data_id = '_'.join(data_list)
        sha = hashlib.sha1(data_id.encode('utf8'))
        return sha.hexdigest()

    def add(self, config: dict, perf: float):
        """
            perf is larger, the better.
        :param config:
        :param perf:
        :return:
        """
        model_path_id = self.model_dir + self.get_configuration_id(config) + '.pt'
        model_path_removed = None
        save_flag, delete_flag = False, False

        if len(self.sorted_list) == 0:
            self.sorted_list.append((config, perf, model_path_id))
        else:
            # Sorted list is in a descending order.
            for idx, item in enumerate(self.sorted_list):
                if perf > item[1]:
                    self.sorted_list.insert(idx, (config, perf, model_path_id))
                    break

        if len(self.sorted_list) > self.k:
            model_path_removed = self.sorted_list[-1][2]
            delete_flag = True
            self.sorted_list = self.sorted_list[:-1]
        if model_path_id in [item[2] for item in self.sorted_list]:
            save_flag = True
        return save_flag, model_path_id, delete_flag, model_path_removed