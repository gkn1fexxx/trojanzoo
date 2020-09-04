# -*- coding: utf-8 -*-
from .badnet import BadNet
from trojanzoo.utils.mark import Watermark
from trojanzoo.utils.data import MyDataset
from trojanzoo.model.image.trojannet import MLPNet, Combined_Model

import torch
import torch.optim as optim
import numpy as np

import os
from itertools import combinations
from scipy.special import comb

from trojanzoo.utils import Config
env = Config.env


class TrojanNet(BadNet):
    name: str = "trojannet"

    def __init__(self, select_point: int = 5, **kwargs):
        super().__init__(**kwargs)
        self.all_point = self.mark.height * self.mark.width
        self.select_point = select_point

        self.mlp_model = MLPNet(all_point=self.all_point, select_point=self.select_point, dataset=self.dataset)
        self.combined_model = Combined_Model(org_model=self.model._model, mlp_model=self.mlp_model._model,
                                             mark=self.mark, dataset=self.dataset)

    def synthesize_training_sample(self):
        combination_list = np.array(list(combinations(list(range(self.all_point)), self.select_point)))
        np.random.seed(env['seed'])
        np.random.shuffle(combination_list)
        combination_list = torch.tensor(combination_list)

        x = torch.ones(len(combination_list), self.all_point, dtype=torch.float)
        x = x.scatter(dim=1, index=combination_list, src=torch.zeros_like(x))
        y = list(range(len(combination_list)))
        return x, y

    def synthesize_random_sample(self, random_size: int):
        combination_number = int(comb(self.all_point, self.select_point))
        x = torch.rand(random_size, self.all_point) + 2 * torch.rand(1) - 1
        x = x.clamp(0, 1)
        y = [combination_number] * random_size
        return x, y

    def attack(self, epoch: int = 500, optimizer=None, lr_scheduler=None, save=False, get_data='self', loss_fn=None, **kwargs):
        if isinstance(get_data, str) and get_data == 'self':
            get_data = self.get_data
        if isinstance(loss_fn, str) and loss_fn == 'self':
            loss_fn = self.loss_fn
        # Training of trojannet (injected MLP).
        x, y = self.synthesize_training_sample()
        self.mark.org_mark = x[self.target_class].repeat(self.dataset.n_channel, 1).view(self.mark.org_mark.shape)
        self.mark.mark, _, _ = self.mark.mask_mark(height_offset=self.mark.height_offset,
                                                   width_offset=self.mark.width_offset)
        random_x, random_y = self.synthesize_random_sample(2000)
        # train_x = torch.cat((x, random_x[:200]))
        # train_y = y + random_y[:200]
        # valid_x = torch.cat((x, random_x))
        # valid_y = y + random_y
        train_x = x
        train_y = y
        valid_x = x
        valid_y = y

        loader_train = [(train_x, torch.tensor(train_y, dtype=torch.long))]
        loader_valid = [(valid_x, torch.tensor(valid_y, dtype=torch.long))]

        optimizer = torch.optim.Adam(params=self.mlp_model.parameters(), lr=1e-2)
        self.mlp_model._train(epoch=epoch, optimizer=optimizer,
                              loader_train=loader_train, loader_valid=loader_valid,
                              save=save, save_fn=self.save)
        self.validate_func(get_data=self.get_data)

    def save(self, **kwargs):
        filename = self.get_filename(**kwargs)
        file_path = self.folder_path + filename
        self.mlp_model.save(file_path + '.pth')
        print('attack results saved at: ', file_path)

    def load(self, **kwargs):
        filename = self.get_filename(**kwargs)
        file_path = self.folder_path + filename
        self.mlp_model.load(file_path + '.pth')
        print('attack results loaded from: ', file_path)

    def validate_func(self, get_data=None, loss_fn=None, **kwargs) -> (float, float, float):
        clean_loss, clean_acc, _ = self.combined_model._validate(print_prefix='Validate Clean',
                                                                 get_data=None, **kwargs)
        target_loss, target_acc, _ = self.combined_model._validate(print_prefix='Validate Trigger Tgt',
                                                                   get_data=self.get_data, keep_org=False, **kwargs)
        _, orginal_acc, _ = self.combined_model._validate(print_prefix='Validate Trigger Org',
                                                          get_data=self.get_data, keep_org=False, poison_label=False, **kwargs)
        # todo: Return value
        if self.clean_acc - clean_acc > 3 and self.clean_acc > 40:
            target_acc = 0.0
        return clean_loss + target_loss, target_acc, clean_acc