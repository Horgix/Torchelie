import functools

import torch
import torch.nn as nn
from torchelie.utils import layer_by_name


class WithSavedActivations(nn.Module):
    def __init__(self, model, types=(nn.Conv2d, nn.Linear), names=None):
        super(WithSavedActivations, self).__init__()
        self.model = model
        self.activations = {}
        self.detach = True

        if names is None:
            for name, layer in self.model.named_modules():
                if isinstance(layer, types):
                    layer.register_forward_hook(functools.partial(
                        self._save, name))
        else:
            for n in names:
                layer = layer_by_name(model)
                layer.register_forward_hook(functools.partial(
                    self._save, name))


    def _save(self, name, module, input, output):
        if self.detach:
            self.activations[name] = output.detach().clone()
        else:
            self.activations[name] = output.clone()

    def forward(self, input, detach):
        self.detach = detach
        self.activations = {}
        out = self.model(input)
        acts = self.activations
        self.activations = {}
        return out, acts
