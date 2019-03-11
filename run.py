from __future__ import print_function

"""
Requires izhi2003a.mod from:
https://senselab.med.yale.edu/ModelDB/showmodel.cshtml?model=39948

Run this script from the same directory as the compiled izhi2003a.mod

NB: on OSX, run using `pythonw` (first, `conda install python.app`) for plotting to work
"""

import os
import json
import itertools
import logging as log
from argparse import ArgumentParser
from datetime import datetime

import numpy as np
import matplotlib.pyplot as plt
import h5py
# from pynwb import NWBFile, NWBHDF5IO, TimeSeries

from stimulus import stims, add_stims

try:
    from mpi4py import MPI
    mpi = True
    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()
    n_tasks = comm.Get_size()
except:
    mpi = False
    comm = None
    rank = 0
    n_tasks = 1
    
from neuron import h, gui

log.basicConfig(format='%(asctime)s %(message)s', level=log.DEBUG)

DEFAULT_PARAMS = {
    'izhi': (0.02, 0.2, -65., 2.),
    'hh': (.12, .036, 0.1, .0003, 1.0),
}
NPARAMS = {
    'izhi': 4,
    'hh': 5,
}

range_a = (0.01, 0.1)
range_b = (0.1, 0.4)
range_c = (-80, -50)
range_d = (0.5, 10)

range_gnabar = (0.08, 0.2)
range_gkbar = (0.02, 0.05)
range_gcabar = (0.5, 0.15)
range_gl = (0.0015, 0.0045)
range_cm = (0.7, 1.3)

RANGES = {
    'izhi': (range_a, range_b, range_c, range_d),
    'hh': (range_gnabar, range_gkbar, range_gcabar, range_gl, range_cm),
}

NSAMPLES = 10000


def ndim(args):
    if args.model == 'izhi':
        return NPARAMS['izhi']
    elif args.model == 'hh':
        return NPARAMS['hh']
    
def myadvance():
    idx = int(h.t/h.dt)
    if idx < len(h.stim):
        h.cell.Iin = h.stim[int(h.t/h.dt)]
    h.fadvance()

def _rangeify(data, _range):
    return data * (_range[1] - _range[0]) + _range[0]


def get_random_params(args, n=1):
    if args.model == 'izhi':
        return get_random_params_izhi(n=n)
    elif args.model == 'hh':
        return get_random_params_hh(n=n)
    else:
        raise ValueError("choose either 'izhi' or 'hh'")

    
def get_random_params_izhi(n=1):
    ndim = NPARAMS['izhi']
    
    rand = np.random.rand(n, ndim)
    rand[:, 0] = _rangeify(rand[:, 0], range_a)
    rand[:, 1] = _rangeify(rand[:, 1], range_b)
    rand[:, 2] = _rangeify(rand[:, 2], range_c)
    rand[:, 3] = _rangeify(rand[:, 3], range_d)

    return rand


def get_random_params_hh(n=1):
    ndim = NPARAMS['hh']

    rand = np.random.rand(n, ndim)
    rand[:, 0] = _rangeify(rand[:, 0], range_gnabar)
    rand[:, 1] = _rangeify(rand[:, 1], range_gkbar)
    rand[:, 2] = _rangeify(rand[:, 2], range_gcabar)
    rand[:, 3] = _rangeify(rand[:, 3], range_gl)
    rand[:, 4] = _rangeify(rand[:, 4], range_cm)

    return rand


def get_mpi_idx(nsamples=NSAMPLES):
    params_per_task = (nsamples // n_tasks) + 1
    start = params_per_task * rank
    stop = min(params_per_task * (rank + 1), nsamples)
    log.info("There are {} ranks, so each rank gets {} param sets".format(n_tasks, params_per_task))
    log.info("This rank is processing param sets {} through {}".format(start, stop))

    return start, stop


def get_params_mpi(nsamples=NSAMPLES):
    """
    Get the list of parameter sets for this MPI task
    """
    paramsets = get_paramsets(nsamples=nsamples)
    start, stop = get_mpi_idx(nsamples=nsamples)

    return paramsets[start:stop], start, stop


multiplier = {
    'Ramp_0p5.csv': 30.0,
    'Step_0p2.csv': 30.0,
    'chirp_05.csv': 10.0,
    'chirp_damp.csv': 15.0,
    'chirp_damp_8k.csv': 15.0,
    'he_1i_1.csv': 20.0,
}
def get_stim(args):
    # TODO?: variable length stimuli, or determine simulation duration from stimulus length?
    if args.stim_file:
        stim_fn = os.path.basename(args.stim_file)
        stim = np.genfromtxt(args.stim_file, dtype=np.float64) * multiplier[stim_fn]
    else:
        stim = stims[args.stim_type][args.stim_idx]

    silence = np.zeros(int(args.silence/args.dt))

    return np.concatenate([silence, stim, silence])


def attach_stim(args):
    if args.model == 'izhi':
        # redefine NEURON's advance() (runs one timestep) to update the current
        h('proc advance() {nrnpython("myadvance()")}')
    elif args.model == 'hh':
        # Use an IClamp object
        h('objref clamp')
        clamp = h.IClamp(0.5)
        clamp.delay = 0
        clamp.dur = 100
        h.clamp = clamp

        h('objref stimvals')
        stimvals = h.Vector().from_python(h.stim)
        h.stimvals = stimvals
        stimvals.play("clamp.amp = $1", h.dt)
    else:
        raise ValueError("choose 'izhi' or 'hh'")


def create_h5(args, nsamples=NSAMPLES):
    """
    Run in serial mode
    """
    # TODO: tstop, rate, and other parameters
    log.info("Creating h5 file")
    with h5py.File(args.outfile, 'w') as f:
        # write params
        ndim = NPARAMS[args.model]
        f.create_dataset('phys_par', shape=(nsamples, ndim))
        f.create_dataset('norm_par', shape=(nsamples, ndim), dtype=np.float64)

        # write param range
        phys_par_range = np.stack([range_a, range_b, range_c, range_d])
        f.create_dataset('phys_par_range', data=phys_par_range, dtype=np.float64)

        # create stim and voltage datasets
        stim = get_stim(args)
        ntimepts = int(args.tstop/args.dt)
        f.create_dataset('voltages', shape=(nsamples, ntimepts), dtype=np.float64)
        f.create_dataset('stim', data=stim)

    log.info("Done.")


def _normalize(args, data, minmax=1):
    nsamples = data.shape[0]
    mins = np.array([tup[0] for tup in RANGES[args.model]])
    mins = np.tile(mins, (nsamples, 1)) # stacked to same shape as input
    ranges = np.array([tup[1]-tup[0] for tup in RANGES[args.model]])
    ranges = np.tile(ranges, (nsamples, 1))

    return 2*minmax * ( (data - mins)/ranges ) - minmax

    
def save_h5(args, buf, params, start, stop):
    log.info("saving into h5")
    if comm and n_tasks > 1:
        log.info("using parallel")
        kwargs = {'driver': 'mpio', 'comm': comm}
    else:
        log.info("using serial")
        kwargs = {}
    with h5py.File(args.outfile, 'a', **kwargs) as f:
        log.info("opened h5")
        f['phys_par'][start:stop, :] = params
        mins, maxes = np.min(params, axis=0), np.max(params, axis=0)
        f['norm_par'][start:stop, :] = _normalize(args, params)
        f['voltages'][start:stop, :] = buf
        log.info("saved h5")
    log.info("closed h5")


def create_nwb(args):
    log.info("Creating and writing nwb file {}...".format(args.outfile))
    nwb = NWBFile(
        session_description='izhikevich simulation',
        identifier='izhi',
        session_start_time=datetime.now(),
        file_create_date=datetime.now(),
        experimenter='Vyassa Baratham',
        experiment_description='izhikevich simulations for DL',
        session_id='izhi',
        institution='LBL/UCB',
        lab='NSE Lab',
        pharmacology='',
        notes='',
    )
    add_stims(nwb)
    with NWBHDF5IO(args.outfile, 'w') as io:
        io.write(nwb)
    log.info("Done.")


def save_nwb(args, v, a, b, c, d):
    # outfile must exist
    log.info("Saving nwb...")
    
    with NWBHDF5IO(args.outfile, 'a', comm=comm) as io:
        nwb = io.read()
        params_dict = {'a': a, 'b': b, 'c': c, 'd': d}

        stim_str = '{}_{:02d}'.format(args.stim_type, args.stim_idx)
        param_str = hash((a, b, c, d))
        dset_name = '{}__{}'.format(stim_str, param_str)
        dset = TimeSeries(name=dset_name, data=v, description=json.dumps(params_dict),
                          starting_time=0.0, rate=1.0/h.dt)
        nwb.add_acquisition(dset)

        io.write(nwb)
        
    log.info("done.")
    

def plot(args, stim, v):
    t_axis = np.linspace(0, len(v)*h.dt, len(v)-1)

    if args.plot_stim:
        plt.plot(t_axis, stim[:len(v)-1])
        plt.show()
    
    if args.plot_v:
        plt.plot(t_axis, v[:-1])
        plt.show()

    # if args.plot_u:
    #     plt.plot(t_axis, u[:-1])
    #     plt.show()


def silence_spikes(v, args):
    npts = int(args.silence/args.dt)
    return max(v[:npts]) > 0


def simulate(args, params):
    _start = datetime.now()

    # Simulation parameters
    h.tstop = args.tstop
    h.steps_per_ms = 1./args.dt
    h.stdinit() # sets h.dt based on h.steps_per_ms
    ntimepts = int(h.tstop/h.dt)

    if h.dt != args.dt:
        raise ValueError("Invalid choice of dt")

    # Define the cell
    # This doesn't work when done in a separate function, for some reason
    # I think 'dummy' needs to stay in scope?
    v = h.Vector(ntimepts)
    if args.model == 'izhi':
        dummy = h.Section()
        cell = h.Izhi2003a(0.5,sec=dummy)
        
        a, b, c, d = params
        cell.a = a
        cell.b = b
        cell.c = c
        cell.d = d
        
        v.record(cell._ref_V)
    elif args.model == 'hh':
        cell = h.Section()
        cell.insert('hh')
        cell.insert('ca')
        hh = cell(0.5).hh
        ca = cell(0.5).ca

        gnabar, gkbar, gcabar, gl, cm = params
        hh.gnabar = gnabar
        hh.gkbar = gkbar
        hh.gl = gl
        ca.gbar = gcabar
        cell.cm = cm

        v.record(cell(0.5)._ref_v)
    else:
        raise ValueError("choose 'izhi' or 'hh'")

    # Define the stimulus
    stim = get_stim(args)

    # Make the stimulus and cell objects accessible from hoc
    h('objref stim')
    h.stim = stim
    h('objref cell')
    h.cell = cell

    # attach the stim to the cell
    attach_stim(args)
    
    # Set up recordings of u and v
    # u = h.Vector(ntimepts)
    # u.record(cell._ref_u)

    # v = h.Vector(ntimepts)
    # v.record(cell._ref_V)

    # Run
    log.info("Running simulation for {} ms with dt = {}".format(h.tstop, h.dt))
    log.info("({} total timesteps)".format(ntimepts))

    h.run()

    log.info("Time to simulate: {}".format(datetime.now() - _start))

    # numpy-ify
    # u = np.array(u)
    v = np.array(v)

    # Plot
    plot(args, stim, v)

    return v

def main(args):

    if not any([args.plot_stim, args.plot_u, args.plot_v, args.outfile, args.force]):
        raise ValueError("You didn't choose to plot or save anything. "
                         + "Pass --force to continue anyways")

    if args.param_file:
        all_paramsets = np.genfromtxt(args.param_file, dtype=np.float64)
        start, stop = get_mpi_idx(len(all_paramsets))
        paramsets = all_paramsets[start:stop, :]
    elif args.num:
        start, stop = get_mpi_idx(args.num)
        paramsets = get_random_params(args, n=stop-start)
    elif args.params not in (None, [None]):
        paramsets = np.atleast_2d(np.array(args.params))
        start, stop = 0, 1
    else:
        log.info("Cell parameters not specified, running with default parameters")
        paramsets = [ DEFAULT_PARAMS[args.model] ]
        start, stop = 0, 1

    bad_params = []
    ntimepts = int(args.tstop/args.dt)
    buf = np.zeros(shape=(stop-start, ntimepts), dtype=np.float64)

    for i, params in enumerate(paramsets):
        if i % 100 == 0:
            log.info(str(i))
        log.info("About to run with params = {}".format(params))
        v = simulate(args, params)
        buf[i, :] = v[:-1]
        
    # Save to disk
    if args.outfile:
        # save_nwb(args, v, a, b, c, d)
        save_h5(args, buf, paramsets, start, stop)


if __name__ == '__main__':
    parser = ArgumentParser()

    parser.add_argument('--model', choices=['izhi', 'hh'], default='izhi')

    parser.add_argument('--outfile', type=str, required=False, default=None,
                        help='nwb file to save to. Must exist.')
    parser.add_argument('--create', action='store_true', default=False,
                        help="create the file, store all stimuli, and then exit")
    parser.add_argument('--create-params', action='store_true', default=False,
                        help="create the params file (--param-file) and exit")

    parser.add_argument('--plot-v', action='store_true', default=False)
    parser.add_argument('--plot-u', action='store_true', default=False)
    parser.add_argument('--plot-stim', action='store_true', default=False)
    
    parser.add_argument('--force', action='store_true', default=False,
                        help="make the script run even if you don't plot or save anything")

    parser.add_argument('--tstop', type=int, default=160)
    parser.add_argument('--dt', type=float, default=.02)

    parser.add_argument('--silence', type=int, default=0,
                        help="amount of pre/post-stim silence (ms)")

    # CHOOSE PARAMETERS
    parser.add_argument('--params', type=float, nargs='+', default=None)
    parser.add_argument('--num', type=int, default=None, required=False,
                        help="number of param values to choose. Will choose randomly. This is the total number over all ranks")
    parser.add_argument('--param-file', type=str, required=False, default=None)

    # CHOOSE STIMULUS
    parser.add_argument('--stim-type', type=str, default='ramp')
    parser.add_argument('--stim-idx', '--stim-i', type=int, default=0)
    parser.add_argument('--stim-file', type=str, required=False, default=None,
                        help="Use a csv for the stimulus file, overrides --stim-type and --stim-idx")# and --tstop")
    
    args = parser.parse_args()

    args.tstop += 2 * args.silence

    if args.create:
        create_h5(args, nsamples=(args.num or NSAMPLES))
        # create_nwb(args)
    elif args.create_params:
        np.savetxt("params/hh_v1.csv", get_random_params(args, n=10000))
    else:
        main(args)
