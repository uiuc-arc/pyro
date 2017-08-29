import torch
from torch.autograd import Variable
from collections import OrderedDict
import pyro
import pyro.poutine as poutine
# from pyro.infer.abstract_infer import AbstractInfer


class KL_QP(object):  # AbstractInfer):
    """
    :param model: probabilistic model defined as a function
    :param guide: guide used for sampling defined as a function
    :param optim: optimization function
    :param model_fixed: flag for if the model is fixed
    :type model_fixed: bool
    :param guide_fixed: flag for if the guide is fixed
    :type guide_fixed: bool

    This method performs variational inference by minimizing the
    `KL-divergence <https://en.wikipedia.org/wiki/Kullback%E2%80%93Leibler_divergence>`_
    between the actual and approximate posterior.

    Example::

        from pyro.infer.kl_qp import KL_QP

        kl_optim = KL_QP(model, guide,
                         pyro.optim(torch.optim.Adam, {"lr": .001}))
        for k in range(n_steps):
        # optimize
        kl_optim.step()
    """
    def __init__(self, model,
                 guide,
                 optim_step_fct,
                 model_fixed=False,
                 guide_fixed=False, *args, **kwargs):
        """
        Call parent class initially, then setup the poutines to run
        """
        # initialize
        super(KL_QP, self).__init__()
        # TODO init this somewhere else in a more principled way
        self.sites = None

        self.model = model
        self.guide = guide
        self.optim_step_fct = optim_step_fct
        self.model_fixed = model_fixed
        self.guide_fixed = guide_fixed

    def __call__(self, *args, **kwargs):
        return self.step(*args, **kwargs)

    def step(self, *args, **kwargs):
        """
        Takes a single step of optimization
        """

        guide_trace = poutine.trace(self.guide)(*args, **kwargs)
        model_trace = poutine.trace(
            poutine.replay(self.model, guide_trace))(*args, **kwargs)

        # compute losses
        log_r = model_trace.log_pdf() - guide_trace.log_pdf()

        elbo = 0.0
        for name in model_trace.keys():
            if model_trace[name]["type"] == "observe":
                elbo += model_trace[name]["log_pdf"]
            elif model_trace[name]["type"] == "sample":
                if model_trace[name]["fn"].reparameterized:
                    elbo += model_trace[name]["log_pdf"]
                    elbo -= guide_trace[name]["log_pdf"]
                else:
                    elbo += Variable(log_r.data) * guide_trace[name]["log_pdf"]
            else:
                pass

        # accumulate parameters
        all_trainable_params = []
        # get trace params from last model run
        if not self.model_fixed:
            for name in model_trace.keys():
                if model_trace[name]["type"] == "param":
                    all_trainable_params.append(model_trace[name]["value"])
        # get trace params from last guide run
        if not self.guide_fixed:
            for name in guide_trace.keys():
                if guide_trace[name]["type"] == "param":
                    all_trainable_params.append(guide_trace[name]["value"])
        all_trainable_params = list(set(all_trainable_params))

        # gradients
        loss = -elbo
        loss.backward()
        # update
        self.optim_step_fct(all_trainable_params)
        # zero grads
        pyro.util.zero_grads(all_trainable_params)

        return loss.data[0]