"""Check unconnected SWC vertices that segment-based clearance cannot cover."""

import numpy as np


def validate_isolated_root_arrays(points_um, radii_um, parents, contacts_um, clearance_um):
    """Check isolated roots in already validated, index-addressed SWC arrays."""
    points = np.asarray(points_um, dtype=float)
    radii = np.asarray(radii_um, dtype=float)
    parent_indices = np.asarray(parents)
    contacts = np.asarray(contacts_um, dtype=float)
    n = len(points)
    if (points.shape != (n, 3) or radii.shape != (n,) or parent_indices.shape != (n,)
            or parent_indices.dtype.kind != "i" or contacts.shape != (2, 3)
            or not np.isfinite(points).all() or not np.isfinite(radii).all()
            or not np.isfinite(contacts).all() or np.any(radii < 0)
            or isinstance(clearance_um, bool | np.bool_)
            or not isinstance(clearance_um, int | float | np.integer | np.floating)
            or not np.isfinite(clearance_um) or clearance_um <= 0
            or np.any(parent_indices < -1) or np.any(parent_indices >= n)):
        raise ValueError("Invalid isolated root geometry")
    children = parent_indices[parent_indices >= 0]
    child_counts = np.bincount(children, minlength=n)
    roots = (parent_indices == -1) & (child_counts == 0)
    if np.any(roots):
        for contact in contacts:
            distances = np.linalg.norm(points[roots] - contact, axis=1)
            if np.any(distances <= clearance_um + radii[roots]):
                raise ValueError("Contact exclusion sphere intersects an isolated SWC vertex")


def validate_isolated_roots(swc, contacts_um, clearance_um):
    """Apply contact clearance to isolated source vertices without inventing edges.

    SWC syntax and contact parameters must already be validated by the caller.
    Coordinates and radii in registered MaleCNS SWC are in 8 nm units.
    """
    rows = [line.split() for line in swc.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    parents = {int(row[6]) for row in rows if int(row[6]) != -1}
    contacts = np.asarray(contacts_um, dtype=float)
    for row in rows:
        if int(row[6]) != -1 or int(row[0]) in parents:
            continue
        center = np.asarray([float(value) * .008 for value in row[2:5]])
        radius = float(row[5]) * .008
        if np.any(np.linalg.norm(contacts - center, axis=1) <= clearance_um + radius):
            raise ValueError("Contact exclusion sphere intersects an isolated SWC vertex")
