# Licensed under a 3-clause BSD style license - see LICENSE.rst

"""Class to represent an astronomical survey."""

from collections import OrderedDict
from copy import deepcopy

import numpy as np
from astropy.table import Table
from astropy import cosmology

from . import models

__all__ = ['Bandpass', 'Spectrum', 'Survey']

# Constants for Survey
wholesky_sqdeg = 4. * np.pi * (180. / np.pi) ** 2

# Constants for Spectrum
h_erg_s = 6.626068e-27  # Planck constant (erg * s)
c_AA_s = 2.9979e+18  # Speed of light ( AA / sec)

default_cosmology = cosmology.WMAP7

class Bandpass(object):
    """A bandpass, e.g., filter. ('filter' is a built-in python function.)

    Parameters
    ----------
    wavelengths : list_like
        Wavelength values, in angstroms
    transmission : list_like
        Transmission values.
    copy : bool, optional
        Copy input arrays.
    """

    def __init__(self, wavelengths, transmission):
        
        self._wavelengths = np.asarray(wavelengths)
        self._transmission = np.asarray(transmission)
        if self._wavelengths.shape != self._transmission.shape:
            raise ValueError('shape of wavelengths and transmission must match')
        if self._wavelengths.ndim != 1:
            raise ValueError('only 1-d arrays supported')

    @property
    def wavelengths(self):
        """Wavelengths in Angstroms"""
        return self._wavelengths

    @property
    def transmission(self):
        """Transmission fraction"""
        return self._transmission


class Spectrum(object):
    """A spectrum, representing wavelength and flux values.

    Parameters
    ----------
    wavelength : list_like
        Wavelength values, in angstroms
    flux : list_like
        Flux values, in units :math:`F_\lambda` (ergs/s/cm^2/Angstrom)
    fluxerr : list_like, optional
        1 standard deviation uncertainty on flux values.
    z : float, optional
        Redshift of spectrum (default is ``None``)
    dist : float, optional
        Luminosity distance in Mpc, used to adjust flux upon redshifting.
        The default is ``None``.
    meta : OrderedDict, optional
        Metadata.
    copy : bool, optional
        Copy input arrays.
    """

    def __init__(self, wavelengths, flux, fluxerr=None, z=None, dist=None,
                 meta=None):
        
        self._wavelengths = np.asarray(wavelengths)
        self._flux = np.asarray(flux)
        
        if self._wavelengths.shape != self._flux.shape:
            raise ValueError('shape of wavelength and flux must match')
        if self._wavelengths.ndim != 1:
            raise ValueError('only 1-d arrays supported')
        self._z = z
        self._dist = dist
        if fluxerr is not None:
            self._fluxerr = np.asarray(fluxerr)
            if self._wavelengths.shape != self._fluxerr.shape:
                raise ValueError('shape of wavelength and variance must match')
        else:
            self._fluxerr = None
        if meta is not None:
            self.meta = deepcopy(meta)
        else:
            self.meta = None

    @property
    def wavelengths(self):
        """Wavelengths of spectrum in Angstroms"""
        return self._wavelengths
        
    @property
    def flux(self):
        """Fluxes in ergs/s/cm^2/Angstrom"""
        return self._flux

    @property
    def fluxerr(self):
        """Fluxes in ergs/s/cm^2/Angstrom"""
        return self._fluxerr

    @property
    def z(self):
        """Redshift of spectrum."""
        return self._z

    @z.setter
    def z(self, value):
        self._z = value

    @property
    def dist(self):
        """Distance to object."""
        return self._dist

    @dist.setter
    def dist(self, value):
        self._dist = value


    def synphot(self, band):
        """Perform synthentic photometry in a given bandpass.
      
        Parameters
        ----------
        band : Bandpass object

        Returns
        -------
        flux : float
            Total flux in photons/sec/cm^2
        fluxerr : float
            Error on flux. Only returned if spectrum.fluxerr is not `None`.
        """

        # If the bandpass is not fully inside the defined region of the spectrum
        # return None.
        if (band.wavelengths[0] < self._wavelengths[0] or
            band.wavelengths[-1] > self._wavelengths[-1]):
            return None

        # Get the spectrum index range to use
        idx = ((self._wavelengths > band.wavelength[0]) & 
               (self._wavelengths < band.wavelength[-1]))

        # Spectrum quantities in this wavelength range
        wl = self._wavelengths[idx]
        f = self._flux[idx]
        binwidth = np.gradient(wl) # Width of each bin

        # Interpolate bandpass transmission to these wavelength values
        trans = np.interp(wl, band.wavelengths, band.transmission)

        # Convert flux from erg/s/cm^2/AA to photons/s/cm^2/AA
        factor = wl / (h_erg_s * c_AA_s)
        f *= factor

        # Get total erg/s/cm^2
        ftot = np.sum(f * trans * binwidth)

        if self._fluxerr is None:
            return ftot
        else:
            fe = self._fluxerr[idx]
            fe *= factor  # Convert from erg/s/cm^2/AA to photons/s/cm^2/AA
            fetot = np.sum((fe * trans) ** 2 * binwidth)
            return totflux, fetot


    def redshifted_to(self, z, adjust_flux=False, dist=None, cosmo=None):
        """Return a new Spectrum object at a new redshift.

        The current redshift must be defined (self.z cannot be `None`).
        A factor of (1 + z) / (1 + self.z) is applied to the wavelength. 
        The inverse factor is applied to the flux so that the bolometric
        flux remains the same.
        
        Parameters
        ----------
        z : float
            Target redshift.
        adjust_flux : bool, optional
            If True, the bolometric flux is adjusted by
            ``F_out = F_in * (D_in / D_out) ** 2``, where ``D_in`` and
            ``D_out`` are current and target luminosity distances,
            respectively. ``D_in`` is self.dist. If self.dist is ``None``,
            the distance is calculated from the current redshift and
            given cosmology.
        dist : float, optional
            Output distance in Mpc. Used to adjust bolometric flux if
            ``adjust_flux`` is ``True``. Default is ``None`` which means
            that the distance is calculated from the redshift and the
            cosmology.
        cosmology : `~astropy.cosmology.Cosmology` instance, optional
            The cosmology used to estimate distances if dist is not given.
            Default is ``None``, which results in using the default
            cosmology.

        Returns
        -------
        spec : Spectrum object
            A new spectrum object at redshift z.
        """

        if cosmology is None:
            cosmology = default_cosmology

        # Shift wavelengths, adjust flux so that bolometric flux
        # remains constant.
        factor =  (1. + z) / (1. + self._z)
        wl = self._wavelengths * factor
        f = self._flux / factor
        if self._fluxerr is not None: fe = self._fluxerr / factor
        else: fe = None

        if adjust_flux:
            # Check current distance
            if self._dist is None and self._z == 0.:
                raise ValueError("When current redshift is 0 and adjust_flux "
                                 "is requested, current distance must be "
                                 "defined")

            # Check requested distance
            if dist is None and z == 0.:
                raise ValueError("When redshift is 0 and adjust_flux "
                                 "is requested, dist must be defined")

            if dist <= 0. or self._dist <= 0.:
                raise ValueError("Distances must be greater than 0.")

            if self._dist is None:
                dist_in = cosmo.luminosity_distance(self._z)
            else:
                dist_in = self._dist

            if dist is None:
                dist_out = cosmo.luminosity_distance(z)
            else:
                dist_out = dist

            # Adjust the flux
            factor = (dist_in / dist) ** 2
            f *= factor
            if fe is not None: fe *= factor ** 2

        return Spectrum(wl, f, fluxerr=fe, z=z, dist=dist, meta=self.meta)


class Survey(object):
    """An astronomical transient survey.

    Parameters
    ----------
    fields: dict
        Information about the observed fields, indexed by field id (int)
    obs : astropy.table.Table, numpy.ndarray, or dict of list_like
        Table of observations in the survey. This table must have certain
        field names. See "Notes" section.
    bandpasses : dict of Bandpass
        Dictionary of bandpasses that the survey should know about.
        The keys should be strings. In the ``obs`` table, ``'band'`` entries are
        strings corresponding to these keys.
    zpspectra : dict of Spectrum
        Dictionary of zeropoint spectra. The keys should be strings. In
        the ``obs`` table, the ``'zpsys'`` field corresponds to these keys.

    Notes
    -----
    The following data fields **must** be in the `obs` table:

        field
            integer id of observed field
        date
            Date of observations in days (e.g., MJD)
        band
            Bandpass of observation (string)
        ccdgain
            CCD gain of observations in e-/ADU
        ccdnoise
            CCD noise of observations in ADU
        skysig
            Pixel-to-pixel standard deviation in background in ADU
        psffwhm
            Full-with at half max (FWHM) of PSF in pixels.
        zp
            Zeropoint of observations (float).
        zpsys
            Zeropoint system (string).

    The following are **optional** fields in the `obs` table
    (not yet implemented - for now these are ignored).

        psf2
            TODO description
        zperr
            Systematic uncertainty in zeropoint.
    """

    def __init__(self, fields, obs, bandpasses, zpspectra):
        self.fields = fields
        self.obs = Table(obs)
        self.bandpasses = bandpasses
        self.zpspectra = zpspectra
        
        # Check that required keys are in the observation table
        required_keys = ['field', 'date', 'band', 'ccdgain', 'ccdnoise',
                         'skysig', 'psffwhm', 'zp', 'zpsys']
        for key in required_keys:
            if not key in self.obs.colnames:
                raise ValueError("observations missing required key: '{}'"
                                 .format(key))

        # Check that observed bands are in self.bandpasses
        uniquebands = np.unique(self.obs['band'])
        for band in uniquebands:
            if not band in self.bandpasses:
                raise ValueError("Bandpass '{}' is in observations, but not"
                                 " in 'bandpasses' dictionary."
                                 .format(band))

        # Check that zeropoint systems are in self.zpspectra
        for name in self.obs['zpsys']:
            if not name in self.zpspectra:
                raise ValueError("zeropoint system '{}' is in observations, "
                                 "but not in 'zpspectra' dictionary."
                                 .format(name))

        # get the zp synthetic flux for all bandpass, zpsys combinations.
        self._zpflux = {}
        for bandname, bandpass in self.bandpasses.iteritems():
            for zpsys, zpspec in self.zpspectra.iteritems():
                self._zpflux[(bandname, zpsys)] = zpspec.synphot(bandpass)


    def simulate(self, tmodel, params, mband, zpspec, vrate=1.e-4, cosmo=None,
                 z_range=(0., 2.), z_bins=40):
        """Run a simulation of the survey.
        
        Parameters
        ----------
        tmodel : A TransientModel instance
            The transient we're interested in.
        params : dictionary or callable
            Dictionary of parameters to pass to the model *or*
            a callable that returns such a dictionary on each call. 
            Typically the callable would randomly select parameters
            from some underlying distribution on each call.
            The parameters must include 'm', the absolute magnitude.
        mband : str
            The rest-frame bandpass in which the absolute magnitude is 
            measured. Must be in the Survey's ``bandpasses`` dictionary.
        zpsys : str
            The zeropoint system of the absolute magnitude ``m``. Must be
            in the Survey's ``zpspectra`` dictionary.
        vrate : float or callable, optional
            The volumetric rate in (comoving Mpc)^{-3} yr^{-1} or
            a callable that returns the rate as a function of redshift.
            (The default is 1.e-4.)
        cosmo : astropy.cosmology.Cosmology, optional
            Cosmology used to determine volumes and luminosity distances.
            (The default is `None`, which implies the WMAP7 cosmology.)
        z_range : (float, float), optional
            Redshift range in which to generate transients.
            The default is (0., 2.).
        z_bins : float, optional
            Number of redshift bins (the default is 40).
        """

        # Check the transient model.
        if not isinstance(tmodel, models.TransientModel):
            raise ValueError('tmodel must be a TransientModel instance')

        # Make params a callable if it isn't already.
        if callable(params):
            getparams = params
        else:
            def getparams(): return params

        # Check that 'm' is in the dictionary that getparams() returns.
        if 'm' not in getparams():
            raise ValueError("params must include 'm'")

        # Check that mband is in bandpasses
        if not mband in self.bandpasses:
            raise ValueError("Requested 'mband' {} not in survey bandpasses."
                             .format(mband))

        # Check that zpsys is in the survey's zpspectra
        if not zpsys in self.zpspectra:
            raise ValueError("Requested 'zpsys' {} not in survey zpspectra."
                             .format(zpsys))

        # Check the volumetric rate.
        if not callable(vrate):
            vrate = lambda z: float(vrate)

        # Check the cosmology.
        if cosmo is None:
            cosmo = default_cosmology
        elif not isinstance(cosmo, cosmology.Cosmology):
            raise ValueError('cosmo must be a Cosmology instance')

        # Check the redshifts
        if len(z_range) != 2:
            raise ValueError('z_range must be length 2')
        z_min, z_max = z_range
        if not (z_max > z_min):
            raise ValueError('z_max must be greater than z_min')
        z_bins = int(z_bins)
        if z_bins < 1:
            raise ValueError('z_bins must be greater than 0')

        # Get volumes in each redshift shell over whole sky
        z_binedges = np.linspace(z_min, z_max, z_bins + 1) 
        sphere_vols = cosmo.comoving_volume(z_binedges) 
        shell_vols = sphere_volumes[1:] - sphere_volumes[:-1]

        # Get list of unique field id's
        fids = np.unique(self.obs['field'])

        # Loop over fields
        for fid in fids:

            # Observations in just this field
            fobs = self.obs(self.obs['field'] == fid)
            
            # Get range of observation dates.
            drange = (fobs['date'].min(), fobs['date'].max())

            # Loop over redshift bins in this field
            for z_lo, z_hi, shell_vol in zip(z_binedges[:-1],
                                             z_binedges[1:],
                                             shell_vols):
                z_mid = (z_lo + z_hi) / 2.
                bin_vol = shell_vol * area / wholesky_sqdeg

                # Simulate transients in a wider date range than the
                # observations. This is the range of dates that phase=0 
                # will be placed at.
                simdrange = (drange[0] - tmodel.phases[-1] * (1 + z_mid),
                             drange[1] - tmodel.phases[0] * (1 + z_mid))
                time_rframe = (simdrange[1] - simdrange[0]) / (1 + z_mid)

                # Number of transients in this bin
                intrinsic_rate = vrate(z_mid) * bin_vol * time_rframe
                ntrans = np.random.poisson(intrinsic_rate, 1)[0]
                if ntrans == 0: continue

                # Where are they in time and redshift?
                dates = np.random.uniform(simdrange[0], simdrange[1], ntrans)
                zs = np.random.uniform(z_lo, z_hi, ntrans)

                # Loop over the transients that occured in this bin
                for i in range(ntrans):
                    date0 = dates[i] # date corresponding to phase = 0
                    z = zs[i]  # redshift of transient

                    # Get a random selection of model parameters.
                    # Do a deep copy in case getparams() returns the same
                    # object each time (we will modify our copy below).
                    params = deepcopy(getparams())

                    # Initialize a data table for this transient
                    transient = {'date0': date0, 'z': z, 'date': [], 'mag': [],
                                 'flux': [], 'fluxerr':[]}
                    
                    # Get mag, flux, fluxerr in each observation in `fobs`
                    for j in range(len(fobs)):
                        
                        phase = (fobs[j]['date'] - date0) / (z + 1)
                        if (phase < tmodel.phases[0] or
                            phase > tmodel.phases[-1]):
                            continue

                        absmag = params.pop('m')
                        spec = Spectrum(tmodel.wavelengths(),
                                        tmodel.flux(phase, **params))
                        
                        # Do synthetic photometry in rest-frame normalizing
                        # band.
                        flux = spec.synphot(self.bandpasses[mband])
                        mag = -2.5 * math.log10(flux /
                                                self._zpflux[(mband, zpsys)])
                        magdiff = absmag - mag

                        # redshift the spectrum
                        #spec.
                        # do synthetic photometry
                        # save results to dict