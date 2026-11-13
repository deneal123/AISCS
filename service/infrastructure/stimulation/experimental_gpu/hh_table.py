"""Prepare the exact NEURON hh rate table used by the experimental solver."""

import numpy as np


def prepare_hh_table():
    """Return 201 rate rows and initial gates at -65 mV, 23 °C.

    This fixed configuration is the currently verified engineering reference,
    not a calibrated Drosophila model. It requires an isolated NEURON process.
    """
    from neuron import h

    if any(True for _ in h.allsec()):
        raise RuntimeError('Rate preparation requires an isolated NEURON process')
    section = h.Section(name='gpu_hh_rates')
    previous_temperature = h.celsius
    previous_table = None
    try:
        section.insert('hh')
        previous_table = h.usetable_hh
        h.setdata_hh(.5, sec=section)
        h.usetable_hh = 0
        h.celsius = 23.
        table = []
        for voltage in range(-100, 101):
            h.rates_hh(voltage)
            hh = section(.5).hh
            table.append([hh.minf, hh.mtau, hh.hinf, hh.htau, hh.ninf, hh.ntau])
        h.rates_hh(-65.)
        initial = np.asarray([section(.5).hh.minf, section(.5).hh.hinf,
                              section(.5).hh.ninf])
        return np.asarray(table), initial
    finally:
        h.celsius = previous_temperature
        if previous_table is not None:
            h.usetable_hh = previous_table
        h.delete_section(sec=section)
