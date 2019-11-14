"""
Just try instantiating all BBP cells and report the ones that error
"""

import os
import json

from neuron import h

from models import BBP

with open('cells.json') as infile:
    cells = json.load(infile)

h.load_file('import3d.hoc')
templates_dir = 'hoc_templates'
with open('problematic_cells.txt', 'w') as outfile:
    for m_type, etypes in cells.items():
        for e_type, clones in etypes.items():
            for i in range(len(clones)):
                import ipdb; ipdb.set_trace()
                cell = BBP(m_type, e_type, i+1)
                cell.create_cell()
