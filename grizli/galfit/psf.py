"""
Generate PSF at an arbitrary position in a drizzled image using the WFC3/IR
effective PSFs.
"""
import os
from collections import OrderedDict

import numpy as np

import astropy.io.fits as pyfits
import astropy.wcs as pywcs

#from research.dash.epsf import DrizzlePSF

DEMO_LIST = ['ib6o23rtq_flt.fits', 'ib6o23rwq_flt.fits', 'ib6o23rzq_flt.fits', 'ib6o23s2q_flt.fits']
DEMO_IMAGE = 'wfc3-ersii-g01-b6o-23-119.0-f140w_drz_sci.fits'

try:
    from .. import utils, model
except:
    from grizli import utils, model
    
class DrizzlePSF(object):
    def __init__(self, flt_files=DEMO_LIST, info=None, driz_image=DEMO_IMAGE):
        """
        Object for making drizzled PSFs
        
        Parameters
        ----------
        flt_files : list
            List of FLT files that were used to create the drizzled image.
        
        driz_image : str
            Filename of the drizzled image.
            
        """
        if info is None:
            self.wcs, self.footprint = self._get_flt_wcs(flt_files)
            self.flt_files = flt_files
        else:
            self.wcs, self.footprint = info
            self.flt_files = list(self.wcs.keys())
        
        self.ePSF = utils.EffectivePSF()
        
        self.driz_image = driz_image
        self.driz_header = pyfits.getheader(driz_image)
        self.driz_wcs = pywcs.WCS(self.driz_header)
        self.driz_pscale = utils.get_wcs_pscale(self.driz_wcs)
        
    @staticmethod
    def _get_flt_wcs(flt_files):
        """
        TBD
        """
        from shapely.geometry import Polygon, Point
        
        wcs = OrderedDict()
        footprint = OrderedDict()
        
        for file in flt_files:
            flt_j = pyfits.open(file)
            wcs[file] = pywcs.WCS(flt_j['SCI',1], relax=True)
            footprint[file] = Polygon(wcs[file].calc_footprint())
        
        return wcs, footprint
    
    def get_driz_cutout(self, ra=53.06967306, dec=-27.72333015, size=15, get_cutout=False):
        xy = self.driz_wcs.all_world2pix(np.array([[ra,dec]]), 0)[0]
        xyp = np.cast[int](np.round(xy))
        N = int(np.round(size*0.128254/self.driz_pscale))
        
        slx = slice(xyp[0]-N, xyp[0]+N)
        sly = slice(xyp[1]-N, xyp[1]+N)
        
        wcs_slice = model.ImageData.get_slice_wcs(self.driz_wcs, slx, sly)
        
        wcs_slice.pscale = utils.get_wcs_pscale(wcs_slice)
        
        # outsci = np.zeros((2*N,2*N), dtype=np.float32)
        # outwht = np.zeros((2*N,2*N), dtype=np.float32)
        # outctx = np.zeros((2*N,2*N), dtype=np.int32)
        if get_cutout:
            os.system("getfits -o sub.fits {0} {1} {2} {3} {3}".format(self.driz_image, xyp[0], xyp[1], 2*N))
            hdu = pyfits.open('sub.fits')
            return slx, sly, hdu
            
        return slx, sly, wcs_slice
    
    @staticmethod
    def _get_empty_driz(wcs):
        sh = (wcs._naxis2, wcs._naxis1)
        outsci = np.zeros(sh, dtype=np.float32)
        outwht = np.zeros(sh, dtype=np.float32)
        outctx = np.zeros(sh, dtype=np.int32)
        return outsci, outwht, outctx
        
    def go(self, ra=53.06967306, dec=-27.72333015):
        import scipy.optimize
        
        self = DrizzlePSF(info=(wcs, footprint), driz_image='cosmos-full-v1.2.8-f160w_drz_sci.fits')
        
        slx, sly, wcs_slice = self.get_driz_cutout(ra=ra, dec=dec)
        xx, yy, drz_cutout = self.get_driz_cutout(ra=ra, dec=dec, get_cutout=True)
        
        psf = self.get_psf(ra=ra, dec=dec, filter='F160W', wcs_slice=wcs_slice)
        
        init = (0, 0, drz_cutout[0].data.sum())
        chi2 = self.objfun(init, self, ra, dec, wcs_slice, filter, drz_cutout)
        
        out = scipy.optimize.minimize(self.objfun, init, args=(self, ra, dec, wcs_slice, filter, drz_cutout), method='Powell', jac=None, hess=None, hessp=None, bounds=None, constraints=(), tol=1.e-3, callback=None, options=None)
        
        psf = self.get_psf(ra=ra+out.x[0]/3600., dec=dec+out.x[1]/3600., filter=filter, wcs_slice=wcs_slice, verbose=False)
        
    @staticmethod
    def objfun(params, self, ra, dec, wcs_slice, filter, drz_cutout):
        xoff, yoff = params[:2]
        psf = self.get_psf(ra=ra+xoff/3600., dec=dec+yoff/3600., filter=filter, wcs_slice=wcs_slice, verbose=False)
        chi2 = ((psf[1].data*params[2] - drz_cutout[0].data)**2).sum()
        print(params, chi2)
        return chi2
        
    def get_psf(self, ra=53.06967306, dec=-27.72333015, filter='F140W', pixfrac=0.1, kernel='point', verbose=True, wcs_slice=None, get_extended=True,
    get_weight=False):
        from drizzlepac.astrodrizzle import adrizzle
        from shapely.geometry import Polygon, Point
        
        pix = np.arange(-13,14)
        
        #wcs_slice = self.get_driz_cutout(ra=ra, dec=dec)
        outsci, outwht, outctx = self._get_empty_driz(wcs_slice)
        
        count = 1
        for file in self.flt_files:
            if self.footprint[file].contains(Point(ra, dec)):
                if verbose:
                    print(file)
                
                xy = self.wcs[file].all_world2pix(np.array([[ra,dec]]), 0)[0]
                xyp = np.cast[int](xy)#+1
                dx = xy[0]-int(xy[0])
                dy = xy[1]-int(xy[1])
                
                psf_xy = self.ePSF.get_at_position(xy[0], xy[1], filter=filter)
                yp, xp = np.meshgrid(pix-dy, pix-dx, sparse=False, indexing='ij')
                if get_extended:
                    extended_data = self.ePSF.extended_epsf[filter]
                else:
                    extended_data = None
                    
                psf = self.ePSF.eval_ePSF(psf_xy, xp, yp, extended_data=extended_data)
                
                if get_weight:
                    fltim = pyfits.open(file)
                    flt_weight = fltim[0].header['EXPTIME']
                else:
                    flt_weight = 1
                    
                N = 13
                psf_wcs = model.ImageData.get_slice_wcs(self.wcs[file], slice(xyp[0]-N, xyp[0]+N+1), slice(xyp[1]-N, xyp[1]+N+1))
                psf_wcs.pscale = utils.get_wcs_pscale(self.wcs[file])
                
                adrizzle.do_driz(psf, psf_wcs, psf*0+flt_weight, wcs_slice, 
                                 outsci, outwht, outctx, 1., 'cps', 1,
                                 wcslin_pscale=1., uniqid=1, 
                                 pixfrac=pixfrac, kernel=kernel, fillval=0, 
                                 stepsize=10, wcsmap=None)
                
                if False:
                    count += 1
                    hdu = pyfits.HDUList([pyfits.PrimaryHDU(), pyfits.ImageHDU(data=psf*100, header=utils.to_header(psf_wcs))])                 
                    ds9.set('frame {0}'.format(count+1))
                    ds9.set_pyfits(hdu)
                
        #ss = 1000000/2
        ss = 1./outsci.sum()
        hdu = pyfits.HDUList([pyfits.PrimaryHDU(), pyfits.ImageHDU(data=outsci*ss, header=utils.to_header(wcs_slice))])
        if False:
            ds9.set('frame 2')
            ds9.set_pyfits(hdu)
        
        return hdu
