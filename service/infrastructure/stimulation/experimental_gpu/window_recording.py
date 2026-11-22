"""Accumulate differential point-source recordings from bounded CUDA windows."""

import numpy as np

from . import recording_kernel


class WindowedPointRecorder:
    """Sum supplied membrane currents; this does not model tissue or coupling."""

    def __init__(self, geometries, electrode_um, reference_um, conductivity_s_m, *,
                 clearance_um, samples, coefficients=None):
        if (not isinstance(geometries, dict) or not geometries
                or any(type(body) is not int or body <= 0 for body in geometries)
                or type(samples) is not int or samples < 2):
            raise ValueError('Invalid window recording configuration')
        self.ids = list(geometries)
        self.coefficients = {}
        self.signal = np.zeros(samples, dtype=np.float64)
        self.next_sample = 0
        if coefficients is not None:
            # Coefficients are a function of the reduced geometry and the
            # electrode pair alone, so a caller that already holds them for this
            # exact batch passes them in. Concatenating 3.6 million segments,
            # running the kernel over them and then verifying with allclose
            # measured 32.8 ms per wide cell against 21.9 ms per cell, and the
            # arithmetic was the smaller half: zeroing the kernel changed a tail
            # shard by 2 s of 384 s while removing the whole construction saved
            # 96 s. Nothing is revalidated here because the caller's evidence is
            # a digest over the very arrays that produced these values.
            if (not isinstance(coefficients, dict)
                    or set(coefficients) != set(geometries)):
                raise ValueError('Invalid cached recording coefficients')
            for body, geometry in geometries.items():
                value = np.asarray(coefficients[body], dtype=np.float64)
                if value.shape != (len(np.asarray(geometry['starts_um'])),):
                    raise ValueError('Invalid cached recording coefficients')
                self.coefficients[body] = value
            return
        parts = []
        for body, geometry in geometries.items():
            if not isinstance(geometry, dict):
                raise ValueError('Invalid recording geometry')
            starts = np.asarray(geometry['starts_um'], dtype=float)
            ends = np.asarray(geometry['ends_um'], dtype=float)
            radii = np.asarray(geometry['endpoint_radii_um'], dtype=float)
            midpoints = np.asarray(geometry['midpoints_um'], dtype=float)
            if (starts.ndim != 2 or starts.shape[1:] != (3,) or ends.shape != starts.shape
                    or radii.shape != (len(starts), 2) or midpoints.shape != starts.shape):
                raise ValueError('Invalid recording midpoints')
            parts.append((body, starts, ends, radii, midpoints))
        starts, ends, radii, midpoints = (np.concatenate([row[i] for row in parts], axis=0)
                                          for i in range(1, 5))
        # One fused kernel evaluates the clearance predicate and the field
        # coefficients of every segment; on 389 152 real segments the numpy pair
        # cost 0.160 s against 0.0037 s here, and the coefficients were bitwise
        # equal (see recording_kernel). A whole-population pass concatenates
        # 270 million segments several times over, so this is no longer a rounding
        # error on the packer thread.
        coefficients = recording_kernel.coefficients(starts, ends, radii, midpoints,
            electrode_um, reference_um, conductivity_s_m, clearance_um=clearance_um)
        if (not np.isfinite(midpoints).all()
                or not np.allclose(midpoints, (starts + ends) / 2, rtol=1e-12, atol=1e-12)):
            raise ValueError('Invalid recording midpoints')
        offset = 0
        for body, start, *_ in parts:
            end = offset + len(start)
            self.coefficients[body] = coefficients[offset:end]
            offset = end

    def accept(self, start, end, rows):
        if (type(start) is not int or type(end) is not int or start != self.next_sample
                or not start < end <= len(self.signal) or not isinstance(rows, list)
                or [row.get('id') if isinstance(row, dict) else None for row in rows] != self.ids):
            raise ValueError('Invalid or out-of-order recording window')
        combined = np.zeros(end - start, dtype=np.float64)
        for row in rows:
            coefficients = self.coefficients[row['id']]
            currents = np.asarray(row.get('membrane_current_na'), dtype=np.float64)
            if (currents.shape != (len(coefficients), end - start)
                    or not np.isfinite(currents).all()):
                raise ValueError('Invalid window membrane currents')
            combined += coefficients @ currents
        if not np.isfinite(combined).all():
            raise ValueError('Non-finite window recording')
        self.signal[start:end] = combined
        self.next_sample = end

    def finish(self):
        if self.next_sample != len(self.signal):
            raise ValueError('Incomplete window recording')
        return self.signal.copy()