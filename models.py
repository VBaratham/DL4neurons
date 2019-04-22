from __future__ import print_function

import sys
import logging as log
from datetime import datetime
from argparse import ArgumentParser

import matplotlib.pyplot as plt
import numpy as np

from neuron import h, gui

class BaseModel(object):
    def __init__(self, *args, **kwargs):
        h.celsius = kwargs.pop('celsius', 33)
        self.log = kwargs.pop('log', print)
        params = {name: arg for name, arg in zip(self.PARAM_NAMES, args)}

        # Model params
        for (var, val) in params.items():
            setattr(self, var, val)

    @property
    def stim_variable_str(self):
        return "clamp.amp"

    def init_hoc(self, dt, tstop):
        h.tstop = tstop
        h.steps_per_ms = 1./dt
        h.stdinit()

    def attach_clamp(self):
        h('objref clamp')
        clamp = h.IClamp(h.cell(0.5))
        clamp.delay = 0
        clamp.dur = h.tstop
        h.clamp = clamp

    def attach_stim(self, stim):
        # assign to self to persist it
        self.stimvals = h.Vector().from_python(stim)
        self.stimvals.play("{} = $1".format(self.stim_variable_str), h.dt)

    def attach_recordings(self, ntimepts):
        hoc_vectors = {
            'v': h.Vector(ntimepts),
            'ina': h.Vector(ntimepts),
            'ik': h.Vector(ntimepts),
            'ica': h.Vector(ntimepts),
            'i_leak': h.Vector(ntimepts),
            'i_cap': h.Vector(ntimepts),
        }
        
        hoc_vectors['v'].record(h.cell(0.5)._ref_v)
        hoc_vectors['ina'].record(h.cell(0.5)._ref_ina)
        hoc_vectors['ica'].record(h.cell(0.5)._ref_ica)
        hoc_vectors['ik'].record(h.cell(0.5)._ref_ik)
        hoc_vectors['i_leak'].record(h.cell(0.5).pas._ref_i)
        hoc_vectors['i_cap'].record(h.cell(0.5)._ref_i_cap)

        return hoc_vectors

    def simulate(self, stim, dt=0.02):
        _start = datetime.now()
        
        ntimepts = len(stim)
        tstop = ntimepts * dt
        self.init_hoc(dt, tstop)

        h('objref cell')
        h.cell = self.create_cell()
        self.attach_clamp()
        self.attach_stim(stim)
        hoc_vectors = self.attach_recordings(ntimepts)

        self.log.debug("Running simulation for {} ms with dt = {}".format(h.tstop, h.dt))
        self.log.debug("({} total timesteps)".format(ntimepts))

        h.run()

        self.log.debug("Time to simulate: {}".format(datetime.now() - _start))

        return {k: np.array(v) for (k, v) in hoc_vectors.items()}


class Izhi(BaseModel):
    PARAM_NAMES = ('a', 'b', 'c', 'd')
    DEFAULT_PARAMS = (0.01, 0.2, -65., 2.)
    PARAM_RANGES = ( (0.01, 0.1), (0.1, 0.4), (-80, -50), (0.5, 5) ) # v5 blind sample 
    # PARAM_RANGES = ( (0.01, 0.1), (0.1, 0.4), (-80, -50), (0.5, 10) ) # v6b, not used
    # PARAM_RANGES = ( (-.03, 0.06), (-1.1, 0.4), (-70, -40), (0, 10) )

    @property
    def stim_variable_str(self):
        return "cell.Iin"

    def create_cell(self):
        self.dummy = h.Section()
        cell = h.Izhi2003a(0.5,sec=self.dummy)

        for var in self.PARAM_NAMES:
            setattr(cell, var, getattr(self, var))

        return cell

    def attach_clamp(self):
        self.log.debug("Izhi cell, not using IClamp")

    def attach_recordings(self, ntimepts):
        vec = h.Vector(ntimepts)
        vec.record(h.cell._ref_V) # Capital V because it's not the real membrane voltage
        return {'v': vec}


class HHPoint5Param(BaseModel):
    PARAM_NAMES = ('gnabar', 'gkbar', 'gcabar', 'gl', 'cm')
    DEFAULT_PARAMS = (500, 10, 1.5, .0005, 0.5)
    PARAM_RANGES = tuple((0.5*default, 2.*default) for default in DEFAULT_PARAMS)
    PARAM_RANGES_v4 = ( (200, 800), (8, 15), (1, 2), (0.0004, 0.00055), (0.3, 0.7) )

    def create_cell(self):
        cell = h.Section()
        cell.insert('na')
        cell.insert('kv')
        cell.insert('ca')
        cell.insert('pas')

        cell(0.5).na.gbar = self.gnabar
        cell(0.5).kv.gbar = self.gkbar
        cell(0.5).ca.gbar = self.gcabar
        cell(0.5).pas.g = self.gl
        cell.cm = self.cm

        return cell

class HHBallStick7Param(BaseModel):
    PARAM_NAMES = (
        'gnabar_soma',
        'gnabar_dend',
        'gkbar_soma',
        'gkbar_dend',
        'gcabar_soma',
        'gl_soma',
        'cm'
    )
    DEFAULT_PARAMS = (500, 500, 10, 10, 1.5, .0005, 0.5)
    # PARAM_RANGES = (
    #     (200, 800),
    #     (200, 800),
    #     (8, 15),
    #     (8, 15),
    #     (1, 2),
    #     (0.0004, 0.00055),
    #     (0.3, 0.7)
    # )
    PARAM_RANGES = tuple((0.5*default, 2.*default) for default in DEFAULT_PARAMS)

    DEFAULT_SOMA_DIAM = 21 # source: https://synapseweb.clm.utexas.edu/dimensions-dendrites and Fiala and Harris, 1999, table 1.1

    def __init__(self, *args, **kwargs):
        self.soma_diam = kwargs.pop('soma_diam', self.DEFAULT_SOMA_DIAM)
        self.dend_diam = kwargs.pop('dend_diam', self.DEFAULT_SOMA_DIAM / 10)
        self.dend_length = kwargs.pop('dend_length', self.DEFAULT_SOMA_DIAM * 10)

        super(HHBallStick7Param, self).__init__(*args, **kwargs)
    
    def create_cell(self):
        soma = h.Section()
        soma.L = soma.diam = self.soma_diam
        soma.insert('na')
        soma.insert('kv')
        soma.insert('ca')
        soma.insert('pas')

        dend = h.Section()
        dend.L = self.dend_length
        dend.diam = self.dend_diam
        dend.insert('na')
        dend.insert('kv')

        dend.connect(soma(1))

        # Persist them
        self.soma = soma
        self.dend = dend
        
        for sec in h.allsec():
            sec.cm = self.cm
        for seg in soma:
            seg.na.gbar = self.gnabar_soma
            seg.kv.gbar = self.gkbar_soma
            seg.ca.gbar = self.gcabar_soma
            seg.pas.g = self.gl_soma
        for seg in dend:
            seg.na.gbar = self.gnabar_dend
            seg.kv.gbar = self.gkbar_dend

        return soma

    def attach_recordings(self, ntimepts):
        hoc_vectors = super(HHBallStick7Param, self).attach_recordings(ntimepts)

        hoc_vectors['v_dend'] = h.Vector(ntimepts)
        hoc_vectors['v_dend'].record(self.dend(1)._ref_v) # record from distal end of stick
        
        return hoc_vectors

class HHBallStick4ParamEasy(HHBallStick7Param):
    pass

class HHBallStick9Param(HHBallStick7Param):
    PARAM_NAMES = (
        'gnabar_soma',
        'gnabar_dend',
        'gkbar_soma',
        'gkbar_dend',
        'gcabar_soma',
        'gcabar_dend',
        'gl_soma',
        'gl_dend',
        'cm'
    )
    DEFAULT_PARAMS = (500, 500, 10, 10, 1.5, 1.5, .0005, .0005, 0.5)
    # PARAM_RANGES = tuple((0.7*default, 1.8*default) for default in DEFAULT_PARAMS)
    PARAM_RANGES = tuple((0.5*default, 2.0*default) for default in DEFAULT_PARAMS)

    def create_cell(self):
        super(HHBallStick9Param, self).create_cell()

        self.dend.insert('ca')
        self.dend.insert('pas')
        for seg in self.dend:
            seg.ca.gbar = self.gcabar_dend
            seg.pas.g = self.gl_dend

        return self.soma

class HHTwoDend13Param(HHBallStick9Param):
    PARAM_NAMES = (
        'gnabar_soma',
        'gnabar_apic',
        'gnabar_basal',
        'gkbar_soma',
        'gkbar_apic',
        'gkbar_basal',
        'gcabar_soma',
        'gcabar_apic',
        'gcabar_basal',
        'gl_soma',
        'gl_apic',
        'gl_basal',
        'cm'
    )
    # DEFAULT_PARAMS = (500, 500, 500, 100, 100, 100, 5, 5, 10, .0005, .0005, .0005, 0.5) # Until 10par v1
    DEFAULT_PARAMS = (500, 500, 500, 10, 10, 10, 1.5, 1.5, 1.5, .0005, .0005, .0005, 0.5) # not used yet
    PARAM_RANGES = tuple((0.5*default, 2.0*default) for default in DEFAULT_PARAMS)

    def __init__(self, *args, **kwargs):
        super(HHTwoDend13Param, self).__init__(*args, **kwargs)

        # Rename *_apic to *_dend (super ctor sets them based on PARAM_NAME
        self.gnabar_dend = self.gnabar_apic
        self.gkbar_dend = self.gkbar_apic
        self.gcabar_dend = self.gcabar_apic
        self.gl_dend = self.gl_apic

    def create_cell(self):
        super(HHTwoDend13Param, self).create_cell()

        self.apic = self.dend
        
        self.basal = [h.Section(), h.Section()]

        for sec in self.basal:
            sec.L = self.dend_length / 4.
            sec.diam = self.dend_diam

            sec.connect(self.soma(0))
            
            sec.insert('na')
            sec.insert('kv')
            sec.insert('ca')
            sec.insert('pas')
            for seg in sec:
                seg.na.gbar = self.gnabar_basal
                seg.kv.gbar = self.gkbar_basal
                seg.ca.gbar = self.gcabar_basal
                seg.pas.g = self.gl_basal

            
        return self.soma


MODELS_BY_NAME = {
    'izhi': Izhi,
    'hh_point_5param': HHPoint5Param,
    'hh_ball_stick_7param': HHBallStick7Param,
    'hh_ball_stick_9param': HHBallStick9Param,
    'hh_two_dend_13param': HHTwoDend13Param,
}


if __name__ == '__main__':
    # When executed as a script, this will generate and display traces of the given model at the given params (or its defaults) and overlay a trace with the params shifted 1 rmse
    # parser = ArgumentParser()

    # parser.add_argument('--model', choices=MODELS_BY_NAME.keys(), default='izhi')
    # parser.add_argument('--params', nargs='+', type=float, required=False, default=None)
    # parser.add_argument('--rmse', nargs='+', type=float, required=True)

    # args = parser.parse_args()

    # model_cls = MODELS_BY_NAME[args.model]

    all_rmse = {
        'izhi': [0.0045, 0.011, 0.068, 0.27],
        'hh_point_5param': [rmse * (_max - _min)/2.0 for rmse, (_min, _max)
                            in zip([0.09, 0.39, 0.38, 0.04, 0.05],
                                   HHPoint5Param.PARAM_RANGES)], # could not find rmse valuse in physical units
        # 'hh_point_5param': [rmse * (_max - _min)/2.0 for rmse, (_min, _max)
        #                     in zip([.07, .11, .1, .05, .05],
        #                            HHPoint5Param.PARAM_RANGES_v4)],
        'hh_ball_stick_7param': [49, 55, 1.3, 1.4, 0.16, 1e-5, 0.012],
        'hh_ball_stick_9param': [12, 16, .32, .44, .061, .068, 5.2e-6, 6.8e-6, .0042],
        'hh_two_dend_13param': [51, 34, 110, 12, 9.7, 29, .7, .61, 1.7, 3.9e-5, 2e-5, 7.5e-5, .011],
    }

    print(all_rmse['hh_point_5param'])
    exit()

    STIM_MULTIPLIERS = {
        'izhi': 15.0,
        'hh_point_5param': 20.0,
        'hh_ball_stick_7param': 0.18,
        'hh_ball_stick_9param': 0.3,
        'hh_two_dend_13param': 1.0,
    }
    stim = np.genfromtxt('stims/chirp16a.csv')


    for i, (model_name, model_cls) in enumerate(MODELS_BY_NAME.items()):
        nparam = len(model_cls.PARAM_NAMES)

        plt.figure(figsize=(8, 2*(nparam+2)))
        
        plt.subplot(nparam+2, 1, 1)
        plt.plot(stim, color='red', label='stimulus')
        plt.title("Stimulus")
        plt.legend()

        x_axis = np.linspace(0, len(stim)*0.02, len(stim))
        
        thisstim = stim * STIM_MULTIPLIERS[model_name]

        model = model_cls(*model_cls.DEFAULT_PARAMS, log=log)
        default_trace = model.simulate(thisstim, 0.02)['v'][:len(stim)]
        
        for i, (param_name, rmse) in enumerate(zip(model_cls.PARAM_NAMES, all_rmse[model_name])):
            plt.subplot(nparam+2, 1, i+2)
            plt.title(param_name)

            plt.plot(x_axis, default_trace, label='Default params', color='k')

            params = list(model_cls.DEFAULT_PARAMS)
            params[i] += rmse
            model = model_cls(*params, log=log)
            trace = model.simulate(thisstim, 0.02)
            plt.plot(x_axis, trace['v'][:len(stim)], label='Default + 1 rmse', color='blue')
            
            params = list(model_cls.DEFAULT_PARAMS)
            params[i] -= rmse
            model = model_cls(*params, log=log)
            trace = model.simulate(thisstim, 0.02)
            plt.plot(x_axis, trace['v'][:len(stim)], label='Default - 1 rmse', color='orange')

            plt.gca().get_xaxis().set_visible(False)


        # extreme smears
        plt.subplot(nparam+2, 1, nparam+2)
        plt.title("All param smear")


        params_add = [param + rmse for param, rmse in zip(model_cls.DEFAULT_PARAMS, all_rmse[model_name])]
        params_sub = [param - rmse for param, rmse in zip(model_cls.DEFAULT_PARAMS, all_rmse[model_name])]
        
        plt.plot(x_axis, default_trace, label='Default params', color='k')
        
        model_add = model_cls(*params_add, log=log)
        trace = model_add.simulate(thisstim, 0.02)
        plt.plot(x_axis, trace['v'][:len(stim)], label='Default + 1 rmse', color='blue')

        model_sub = model_cls(*params_sub, log=log)
        trace = model_sub.simulate(thisstim, 0.02)
        plt.plot(x_axis, trace['v'][:len(stim)], label='Default - 1 rmse', color='orange')

        # on the last plot only
        plt.xlabel("Time (ms)")
        plt.legend()

        plt.subplots_adjust(hspace=0.4)

        plt.savefig('pred_actual_voltages/{}.png'.format(model_name))
