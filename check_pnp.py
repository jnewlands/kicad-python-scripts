"""
Script for validating a BOM file against a PNP file.
Both files are key fabrication outputs from KiCad,
and it is imperative that they are consistent.

Input files:
    BOM - Bill of Materials (.csv)
    PNP - Pick and Place (.pos)

DNF:
    If parts are marked as 'DNF' in the schematic,
    they should be removed from the PNP file.
"""

# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import argparse
import os
import re
import csv
import sys

parser = argparse.ArgumentParser(description='KiCad fabrication file checker')

parser.add_argument('-b', '--bom', help='Bill of Materials file')
parser.add_argument('-p', '--pnp', help='Pick and Place file')

args = parser.parse_args()

bom_filename = args.bom
pnp_filename = args.pnp

# Ensure that the PNP file is valid
if not pnp_filename.endswith('.pos'):
    raise ValueError('PNP file must be .pos')

if not os.path.exists(pnp_filename):
    raise FileNotFoundError('PNP file not found: {f}'.format(f=pnp_filename))

# Ensure that the BOM file is valid
if not bom_filename.endswith('.csv'):
    raise ValueError('BOM file must be .csv')

if not os.path.exists(bom_filename):
    raise FileNotFoundError('BOM file not found: {f}'.format(f=bom_filename))

# Map each line in the PNP file to the RefDes
pnp_items = {}

# Keep a list of errors to report at the end
bom_errors = []
pnp_errors = []

# Read the PNP file
with open(pnp_filename, 'r') as pnpfile:

    for line in pnpfile.readlines():

        # Skip lines marked as comments
        if line.startswith('#'):
            continue

        line = line.strip()

        if len(line) == 0:
            continue

        fields = re.split('\s+', str(line.strip()))

        if not len(fields) == 7:
            raise ValueError('Incorrect BOM line: ' + line)

        ref = fields[0]

        if ref in pnp_items.keys():
            raise ValueError('Duplicate RefDes: ' + ref)

        group = {
            'Value': fields[1],
            'Footprint': fields[2],
            'X': fields[3],
            'Y': fields[4],
            'Rotation': fields[5],
            'Side': fields[6],
        }

        pnp_items[ref] = group


# Map each element in the BOM file to the RefDes
bom_items = {}
dnf_count = 0

# Read the BOM file
with open(bom_filename, 'r') as bomfile:

    csvreader = csv.reader(bomfile, delimiter=str(','), quotechar=str('"'))

    headers = []

    for i, row in enumerate(csvreader):

        # First row contains the column headers
        if i == 0:
            headers = []
            for h in row:
                if h.startswith('Quantity'):
                    h = 'Quantity'

                headers.append(h)
            continue

        # First empty row signifies end of file
        if len(row) == 0:
            break

        row_data = {}

        for idx, val in enumerate(row):
            header = headers[idx]
            row_data[headers[idx]] = val

        # Extract the part references
        refs = row_data['References'].split(' ')

        quantity = int(row_data['Quantity'].strip().split(' ')[0])

        if not len(refs) == quantity:
            bom_errors.append('Quantity mismatch: {refs} != {q}'.format(refs=refs, q=quantity))
        
        for ref in refs:
            bom_items[ref] = row_data

missing_from_bom = []
missing_from_pnp = []
extra_in_pnp = []

bom_refs = bom_items.keys()
pnp_refs = pnp_items.keys()

for ref in bom_refs:

    bom_item = bom_items[ref]

    # Should this part be fitted, or not?
    DNF = 'dnf' in bom_item['Quantity'].lower()

    # Part is NOT to be fitted - make sure it IS NOT in the PNP file
    if DNF:
        dnf_count += 1
        if ref in pnp_refs:
            extra_in_pnp.append(ref)
    # Part IS to be fitted - make sure it IS in the PNP file
    else:
        if ref not in pnp_refs:
            missing_from_pnp.append(ref)
        else:
            # Extract this part from the PNP file
            pnp_item = pnp_items[ref]

            # Check footprint data
            fp_bom = bom_item['Footprint']
            fp_pnp = pnp_item['Footprint']

            if not fp_bom == fp_pnp:
                text = "{ref} footprint mismatch - BOM: '{bom}', PNP: '{pnp}'".format(
                    ref=ref,
                    bom=fp_bom,
                    pnp=fp_pnp
                )
                pnp_errors.append(text)

            # Check value data
            val_bom = bom_item['Value']
            val_pnp = pnp_item['Value']

            if not val_bom == val_pnp:
                text = "{ref} value mismatch - BOM '{bom}', PNP: '{pnp}'".format(
                    ref=ref,
                    bom=val_bom,
                    pnp=val_pnp
                )

                pnp_errors.append(text)


for ref in pnp_refs:
    if ref not in bom_refs:
        missing_from_bom.append(ref)

if len(missing_from_bom) > 0:
    bom_errors.append("{n} parts missing from BOM file: {refs}".format(n=len(missing_from_bom), refs=missing_from_bom))

if len(missing_from_pnp) > 0:
    pnp_errors.append("{n} parts missing from PNP file: {refs}".format(n=len(missing_from_pnp), refs=missing_from_pnp))

if len(extra_in_pnp) > 0:
    pnp_errors.append("{n} DNF parts included in PNP file: {refs}".format(n=len(extra_in_pnp), refs=extra_in_pnp))

print("Loaded Component Data:")
bom_str = "BOM items: {n}".format(n=len(bom_items))
if dnf_count > 0:
    bom_str += " (DNF: {n})".format(n=dnf_count)
print(bom_str)
print("PNP Items: {n}".format(n=len(pnp_items)))
print("---------------------")

# Finally, print any pending error messages
if len(bom_errors) > 0:
    print("There are {n} issues found in the BOM file:".format(n=len(bom_errors)))
    for e in bom_errors:
        print("\t- {e}".format(e=e))

if len(pnp_errors) > 0:
    print("There are {n} issues found in the PNP file:".format(n=len(pnp_errors)))
    for e in pnp_errors:
        print("\t- {e}".format(e=e))

sys.exit(len(bom_errors) + len(pnp_errors))