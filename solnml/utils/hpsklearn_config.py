from hyperopt import hp
from hpsklearn import gaussian_nb, liblinear_svc, decision_tree, knn, extra_trees, random_forest, gradient_boosting


def tpe_classifier(name='clf'):
    linear_svc_space = hp.choice('liblinear_combination',
                                 [{'penalty': "l1", 'loss': "squared_hinge", 'dual': False},
                                  {'penalty': "l2", 'loss': "hinge", 'dual': True},
                                  {'penalty': "l2", 'loss': "squared_hinge", 'dual': True},
                                  {'penalty': "l2", 'loss': "squared_hinge", 'dual': False}])
    return hp.choice(name,
                     [gaussian_nb('hpsklearn_gaussian_nb'),
                      liblinear_svc('hpsklearn_liblinear_svc',
                                    C=hp.choice('hpsklearn_liblinear_svc_c',
                                                [1e-4, 1e-3, 1e-2, 1e-1, 0.5, 1., 5., 10., 15., 20., 25.]),
                                    loss=linear_svc_space['loss'],
                                    penalty=linear_svc_space['penalty'],
                                    dual=linear_svc_space['dual'],
                                    tol=hp.choice('hpsklearn_liblinear_svc_tol', [1e-5, 1e-4, 1e-3, 1e-2, 1e-1])
                                    ),
                      decision_tree('decision_tree',
                                    criterion=hp.choice('decision_tree_criterion', ["gini", "entropy"]),
                                    max_depth=hp.randint('decision_tree_max_depth', 10) + 1,
                                    min_samples_split=hp.randint('decision_tree_min_samples_split', 19) + 2,
                                    min_samples_leaf=hp.randint('decision_tree_min_samples_leaf', 20) + 1),
                      knn('knn',
                          n_neighbors=hp.randint('knn_n', 100) + 1,
                          weights=hp.choice('knn_weights', ['uniform', 'distance']),
                          p=hp.choice('knn_p', [1, 2])),
                      extra_trees('et',
                                  n_estimators=100,
                                  criterion=hp.choice('et_criterion', ["gini", "entropy"]),
                                  max_features=hp.randint('et_max_features', 20) * 0.05 + 0.05,
                                  min_samples_split=hp.randint('et_min_samples_split', 19) + 2,
                                  min_samples_leaf=hp.randint('et_min_samples_leaf', 20) + 1,
                                  bootstrap=hp.choice('et_bootstrap', [True, False])),
                      random_forest('rf',
                                    n_estimators=100,
                                    criterion=hp.choice('rf_criterion', ["gini", "entropy"]),
                                    max_features=hp.randint('rf_max_features', 20) * 0.05 + 0.05,
                                    min_samples_split=hp.randint('rf_min_samples_split', 19) + 2,
                                    min_samples_leaf=hp.randint('rf_min_samples_leaf', 20) + 1,
                                    bootstrap=hp.choice('rf_bootstrap', [True, False])),
                      gradient_boosting('gb',
                                        n_estimators=100,
                                        learning_rate=hp.choice('gb_lr', [1e-3, 1e-2, 1e-1, 0.5, 1.]),
                                        max_depth=hp.randint('gb_max_depth', 10) + 1,
                                        min_samples_split=hp.randint('gb_min_samples_split', 19) + 2,
                                        min_samples_leaf=hp.randint('gb_min_samples_leaf', 20) + 1,
                                        subsample=hp.randint('gb_subsample', 20) * 0.05 + 0.05,
                                        max_features=hp.randint('gb_max_features', 20) * 0.05 + 0.05,
                                        )
                      ])
