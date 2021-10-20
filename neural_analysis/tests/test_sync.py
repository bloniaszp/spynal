""" Unit tests for sync.py module """
import pytest
from math import pi
import numpy as np

from scipy.stats import bernoulli

from neural_analysis.utils import index_axis
from neural_analysis.sync import simulate_multichannel_oscillation, synchrony, spike_field_coupling
from neural_analysis.spectra import spectrogram

# =============================================================================
# Fixtures for generating simulated data
# =============================================================================
@pytest.fixture(scope='session')
def oscillation_pair():
    """
    Fixture simulates set of instances of pairs of weakly synchronized oscillatory data
    for unit tests of field-field synchrony computation functions

    RETURNS
    data    (1000,40,2) ndarray. Simulated oscillatory data.
            (eg simulating 1000 timepoints x 40 trials x 2 channels)
    """
    # Note: seed=1 makes data reproducibly match output of Matlab
    frequency = 32
    return simulate_multichannel_oscillation(2, frequency, amplitude=5.0, phase=[pi/4,0], phase_sd=[0,pi/4],
                                             noise=1.0, n_trials=40, time_range=1.0, smp_rate=1000, seed=1)


@pytest.fixture(scope='session')
def spike_field_pair(oscillation_pair):
    """
    Fixture simulates set of instances of weakly synchronized oscillatory spike-field data pairs
    for unit tests of spike-field synchrony computation functions

    RETURNS
    spkdata (1000,40) ndarray of bool. Simulated oscillatory spiking data,
            expressed as binary (0/1) spike trains.
            (eg simulating 1000 timepoints x 4 trials or channels)

    lfpdata (1000,40) ndarray of float. Simulated oscillatory LFP data
            (eg simulating 1000 timepoints x 4 trials or channels)
    """
    # todo code up something actually proper (rate-modulated Poisson process?)
    spkdata,lfpdata = oscillation_pair[:,:,0], oscillation_pair[:,:,1]

    # Convert continuous oscillation to probability (range 0-1)
    spkdata = (spkdata - spkdata.min()) / spkdata.ptp()
    spkdata = spkdata**2  # Sparsen high rates some

    # Use probabilities to generate Bernoulli random variable at each time point
    spkdata =  bernoulli.ppf(0.5, spkdata).astype(bool)

    return spkdata, lfpdata


# =============================================================================
# Unit tests
# =============================================================================
@pytest.mark.parametrize('method, spec_method, result',
                         [('coherence', 'wavelet',      (0.2475,0.4795)),
                          ('coherence', 'multitaper',   (0.1046,0.3043)),
                          ('coherence', 'bandfilter',   (0.3490,0.6706)),
                          ('PLV',       'wavelet',      (0.2541,0.3713)),
                          ('PLV',       'multitaper',   (0.0984,0.2228)),
                          ('PLV',       'bandfilter',   (0.3321,0.4528)),
                          ('PPC',       'wavelet',      (0.0912,0.3713)),
                          ('PPC',       'multitaper',   (0.0100,0.2228)),
                          ('PPC',       'bandfilter',   (0.1715,0.4528))])
def test_synchrony(oscillation_pair, method, spec_method, result):
    """ Unit tests for synchrony() function """
    # Extract per-channel data and reshape -> (n_trials,n_timepts)
    data1, data2 = oscillation_pair[:,:,0].T, oscillation_pair[:,:,1].T
    data1_orig = data1.copy()
    data2_orig = data2.copy()

    smp_rate = 1000
    method_to_n_freqs   = {'wavelet': 26, 'multitaper':257,  'bandfilter': 3}
    method_to_n_timepts = {'wavelet': 1000, 'multitaper':2,  'bandfilter': 1000}
    n_freqs     = method_to_n_freqs[spec_method]
    n_timepts   = method_to_n_timepts[spec_method]
    freqs_shape = (n_freqs,2) if spec_method == 'bandfilter' else (n_freqs,)

    # Basic test of shape, dtype, value of output.
    # Test values averaged over all timepts, freqs for simplicity
    sync, freqs, timepts, dphi = synchrony(data1, data2, axis=0, method=method,
                                           spec_method=spec_method, return_phase=True,
                                           smp_rate=smp_rate, time_axis=-1)
    assert np.array_equal(data1,data1_orig)     # Ensure input data isn't altered by function
    assert np.array_equal(data2,data2_orig)
    assert sync.shape == (n_freqs, n_timepts)
    assert np.issubdtype(sync.dtype,float)
    assert np.issubdtype(dphi.dtype,float)
    assert np.isclose(sync.mean(), result[0], rtol=1e-4, atol=1e-4)
    assert np.isclose(dphi.mean(), result[1], rtol=1e-4, atol=1e-4)

    # Test for consistent output with return_phase=False
    sync2, freqs2, timepts2 = synchrony(data1, data2, axis=0, method=method,
                                        spec_method=spec_method, return_phase=False,
                                        smp_rate=smp_rate, time_axis=-1)
    assert np.array_equal(data1,data1_orig)     # Ensure input data isn't altered by function
    assert np.array_equal(data2,data2_orig)
    assert freqs2.shape == freqs_shape
    assert timepts2.shape == (n_timepts,)
    assert np.allclose(sync2, sync, rtol=1e-4, atol=1e-4)

    # Test for consistent output with reversed time axis (dphi should change sign, otherwise same)
    # Skip test for multitaper/bandfilter phase, bandfilter sync -- not time-reversal invariant
    sync, freqs, timepts, dphi = synchrony(np.flip(data1,axis=-1), np.flip(data2,axis=-1),
                                           axis=0, method=method, spec_method=spec_method,
                                           return_phase=True, smp_rate=smp_rate, time_axis=-1)
    assert np.array_equal(data1,data1_orig)     # Ensure input data isn't altered by function
    assert np.array_equal(data2,data2_orig)
    # HACK Bandfilter not time-reversal invariant due to initial conditions
    if spec_method != 'bandfilter':
        assert np.isclose(sync.mean(), result[0], rtol=1e-4, atol=1e-4)
    # HACK Only synchrony magnitude -- not phase -- is time-reversal invariant for multitaper
    if spec_method == 'wavelet':
        assert np.isclose(dphi.mean(), -result[1], rtol=1e-4, atol=1e-4)

    # Test for consistent output with channels swapped (dphi should change sign, otherwise same)
    # Skip test for multitaper/bandfilter phase -- not time-reversal invariant
    sync, freqs, timepts, dphi = synchrony(data2, data1, axis=0, method=method,
                                           spec_method=spec_method, return_phase=True,
                                           smp_rate=smp_rate, time_axis=-1)
    assert np.array_equal(data1,data1_orig)     # Ensure input data isn't altered by function
    assert np.array_equal(data2,data2_orig)
    assert np.isclose(sync.mean(), result[0], rtol=1e-4, atol=1e-4)
    if spec_method == 'wavelet':
        assert np.isclose(dphi.mean(), -result[1], rtol=1e-4, atol=1e-4)

    # Test for consistent output with different data array shape (3rd axis)
    sync, freqs, timepts, dphi = synchrony(np.stack((data1,data1),axis=2),
                                           np.stack((data2,data2),axis=2),
                                           axis=0, method=method, spec_method=spec_method,
                                           return_phase=True, smp_rate=smp_rate, time_axis=1)
    assert np.array_equal(data1,data1_orig)     # Ensure input data isn't altered by function
    assert np.array_equal(data2,data2_orig)
    assert freqs.shape == freqs_shape
    assert timepts.shape == (n_timepts,)
    assert sync.shape == (n_freqs, n_timepts, 2)
    assert dphi.shape == (n_freqs, n_timepts, 2)
    assert np.issubdtype(sync.dtype,float)
    assert np.issubdtype(dphi.dtype,float)
    # HACK Loosen tolerance bc this doesn't quite match up for bandfilter (TODO why???)
    assert np.isclose(sync[:,:,0].mean(), result[0], rtol=1e-3, atol=1e-3)
    assert np.isclose(dphi[:,:,0].mean(), result[1], rtol=1e-3, atol=1e-3)

    # Test for consistent output with transposed data dimensionality -> (time,trials)
    sync, freqs, timepts, dphi = synchrony(data1.T, data2.T, axis=-1, method=method,
                                           spec_method=spec_method,return_phase=True,
                                           smp_rate=smp_rate, time_axis=0)
    assert np.array_equal(data1,data1_orig)     # Ensure input data isn't altered by function
    assert np.array_equal(data2,data2_orig)
    assert freqs.shape == freqs_shape
    assert timepts.shape == (n_timepts,)
    assert sync.shape == (n_freqs, n_timepts)
    assert dphi.shape == (n_freqs, n_timepts)
    assert np.issubdtype(sync.dtype,float)
    assert np.issubdtype(dphi.dtype,float)
    assert np.isclose(sync.mean(), result[0], rtol=1e-4, atol=1e-4)
    assert np.isclose(dphi.mean(), result[1], rtol=1e-4, atol=1e-4)

    # Test for consistent output with spectral data input
    extra_args = dict(axis=1, method=spec_method, spec_type='complex')
    if spec_method == 'multitaper': extra_args.update(keep_tapers=True)
    spec1, freqs, timepts = spectrogram(data1, smp_rate, **extra_args)
    spec2, freqs, timepts = spectrogram(data2, smp_rate, **extra_args)
    sync, _, _, dphi = synchrony(spec1, spec2, axis=0, taper_axis=2, method=method,
                                 spec_method=spec_method, return_phase=True)
    assert np.array_equal(data1,data1_orig)     # Ensure input data isn't altered by function
    assert np.array_equal(data2,data2_orig)
    assert freqs.shape == freqs_shape
    assert timepts.shape == (n_timepts,)
    assert sync.shape == (n_freqs, n_timepts)
    assert dphi.shape == (n_freqs, n_timepts)
    assert np.issubdtype(sync.dtype,float)
    assert np.issubdtype(dphi.dtype,float)
    assert np.isclose(sync.mean(), result[0], rtol=1e-4, atol=1e-4)
    assert np.isclose(dphi.mean(), result[1], rtol=1e-4, atol=1e-4)

    # Ensure that passing a nonexistent/misspelled kwarg raises an error
    with pytest.raises((TypeError,AssertionError)):
        sync, freqs, timepts, dphi = synchrony(data1, data2, axis=0, method=method,
                                            spec_method=spec_method, return_phase=True,
                                            smp_rate=smp_rate, time_axis=-1, foo=None)


@pytest.mark.parametrize('method, spec_method, result',
                         [('coherence', 'wavelet',      (0.2400,0.2894)),
                          ('coherence', 'multitaper',   (0.1218,0.1530)),
                          ('coherence', 'bandfilter',   (0.3721,0.2696)),
                          ('PLV',       'wavelet',      (0.1600,-0.2363,1994)),
                          ('PLV',       'multitaper',   (0.0576,0.9140,6032)),
                          ('PLV',       'bandfilter',   (0.3041,-0.2257,1994)),
                          ('PPC',       'wavelet',      (0.0764,-0.2363,1994)),
                          ('PPC',       'multitaper',   (0.0085,0.9140,6032)),
                          ('PPC',       'bandfilter',   (0.1417,-0.2257,1994))])
def test_spike_field_coupling(spike_field_pair, method, spec_method, result):
    """ Unit tests for spike_field_coupling() function """
    # Extract per-channel data and reshape -> (n_trials,n_timepts)
    spkdata, lfpdata = spike_field_pair[0].T, spike_field_pair[1].T
    spkdata_orig = spkdata.copy()
    lfpdata_orig = lfpdata.copy()

    smp_rate = 1000
    method_to_n_freqs   = {'wavelet': 26, 'multitaper':129,  'bandfilter': 3}
    method_to_n_timepts = {'wavelet': 1000, 'multitaper':5,  'bandfilter': 1000} \
                          if method == 'coherence' else \
                          {'wavelet': 4, 'multitaper':4,  'bandfilter': 4}
    n_freqs     = method_to_n_freqs[spec_method]
    n_timepts   = method_to_n_timepts[spec_method]
    freqs_shape = (n_freqs,2) if spec_method == 'bandfilter' else (n_freqs,)
    timepts     = np.arange(lfpdata.shape[-1]) / smp_rate

    extra_args  = {'timepts':timepts, 'width':0.2} if method != 'coherence' else {}
    if (spec_method == 'multitaper'):
        extra_args.update(time_width=0.2, spacing=0.2, freq_width=10)

    # Basic test of shape, dtype, value of output.
    # Test values averaged over all timepts, freqs for simplicity
    sync, freqs, timepts, n, phi = spike_field_coupling(spkdata, lfpdata, axis=0, time_axis=-1,
                                                        method=method, spec_method=spec_method,
                                                        smp_rate=smp_rate, return_phase=True,
                                                        **extra_args)
    assert np.array_equal(spkdata,spkdata_orig)     # Ensure input data isn't altered by function
    assert np.array_equal(lfpdata,lfpdata_orig)
    assert isinstance(freqs, np.ndarray)
    assert isinstance(timepts, np.ndarray)
    assert isinstance(sync, np.ndarray)
    assert isinstance(phi, np.ndarray)
    assert sync.shape == (n_freqs, n_timepts)
    assert freqs.shape == freqs_shape
    assert timepts.shape == (n_timepts,)
    assert phi.shape == (n_freqs, n_timepts)
    assert np.issubdtype(sync.dtype,float)
    assert np.issubdtype(phi.dtype,float)
    assert np.isclose(np.nanmean(sync), result[0], rtol=1e-4, atol=1e-4)
    assert np.isclose(np.nanmean(phi), result[1], rtol=1e-4, atol=1e-4)
    if method != 'coherence':
        assert isinstance(n, np.ndarray)
        assert n.shape == (n_timepts,)
        assert np.round(n.mean()) == result[2]


    # Test for consistent output with return_phase=False
    sync2, freqs2, timepts2, n = spike_field_coupling(spkdata, lfpdata, axis=0, time_axis=-1,
                                                      method=method, spec_method=spec_method,
                                                      smp_rate=smp_rate, return_phase=False,
                                                      **extra_args)
    assert np.array_equal(spkdata,spkdata_orig)     # Ensure input data isn't altered by function
    assert np.array_equal(lfpdata,lfpdata_orig)
    assert freqs2.shape == freqs_shape
    assert timepts2.shape == (n_timepts,)
    assert np.isclose(np.nanmean(sync2), result[0], rtol=1e-4, atol=1e-4)
    if method != 'coherence': assert np.round(n.mean()) == result[2]

    # Test for consistent output with reversed time axis (phi should change sign, otherwise same)
    # Note: Due to windowing, results not time-reveral invariant for PLV/PPC, so skip those
    # Skip test for multitaper/bandfilter phase, bandfilter sync -- not time-reversal invariant
    sync, freqs, timepts, n, phi = spike_field_coupling(np.flip(spkdata,axis=-1),
                                                        np.flip(lfpdata,axis=-1),
                                                        axis=0, time_axis=-1, method=method,
                                                        spec_method=spec_method, smp_rate=smp_rate,
                                                        return_phase=True, **extra_args)
    assert np.array_equal(spkdata,spkdata_orig)     # Ensure input data isn't altered by function
    assert np.array_equal(lfpdata,lfpdata_orig)
    assert sync.shape == (n_freqs, n_timepts)
    assert freqs.shape == freqs_shape
    assert timepts.shape == (n_timepts,)
    assert phi.shape == (n_freqs, n_timepts)
    # HACK Bandfilter not time-reversal invariant due to initial conditions
    if (spec_method != 'bandfilter') and (method not in ['PLV','PPC']):
        assert np.isclose(np.nanmean(sync), result[0], rtol=1e-4, atol=1e-4)
    # HACK Only synchrony magnitude -- not phase -- is time-reversal invariant for multitaper
    if (spec_method == 'wavelet') and (method not in ['PLV','PPC']):
        assert np.isclose(np.nanmean(phi), -result[1], rtol=1e-4, atol=1e-4)

    # Test for consistent output with different data array shape (3rd axis)
    if method == 'coherence':
        sync, freqs, timepts, n, phi = spike_field_coupling(np.stack((spkdata,spkdata),axis=2),
                                                            np.stack((lfpdata,lfpdata),axis=2),
                                                            axis=0, time_axis=1, method=method,
                                                            spec_method=spec_method, smp_rate=smp_rate,
                                                            return_phase=True, **extra_args)
        assert np.array_equal(spkdata,spkdata_orig)     # Ensure input data isn't altered by function
        assert np.array_equal(lfpdata,lfpdata_orig)
        assert freqs.shape == freqs_shape
        assert timepts.shape == (n_timepts,)
        assert sync.shape == (n_freqs, n_timepts, 2)
        assert phi.shape == (n_freqs, n_timepts, 2)
        assert np.issubdtype(sync.dtype,float)
        assert np.issubdtype(phi.dtype,float)
        assert np.isclose(sync[:,:,0].mean(), result[0], rtol=1e-4, atol=1e-4)
        assert np.isclose(phi[:,:,0].mean(), result[1], rtol=1e-4, atol=1e-4)
        if method != 'coherence': assert np.round(n.mean()) == result[2]

    # Test for consistent output with transposed data dimensionality -> (time,trials)
    sync, freqs, timepts, n, phi = spike_field_coupling(spkdata.T, lfpdata.T,
                                                        axis=-1, time_axis=0, method=method,
                                                        spec_method=spec_method, smp_rate=smp_rate,
                                                        return_phase=True, **extra_args)
    assert np.array_equal(spkdata,spkdata_orig)     # Ensure input data isn't altered by function
    assert np.array_equal(lfpdata,lfpdata_orig)
    if method != 'coherence': print(n.shape, np.round(n.mean()))
    assert freqs.shape == freqs_shape
    assert timepts.shape == (n_timepts,)
    assert sync.shape == (n_freqs, n_timepts)
    assert phi.shape == (n_freqs, n_timepts)
    assert np.issubdtype(sync.dtype,float)
    assert np.issubdtype(phi.dtype,float)
    assert np.isclose(np.nanmean(sync), result[0], rtol=1e-4, atol=1e-4)
    assert np.isclose(np.nanmean(phi), result[1], rtol=1e-4, atol=1e-4)
    if method != 'coherence': assert np.round(n.mean()) == result[2]

    # Test for consistent output with spectral data input
    if spec_method == 'multitaper':
        spec_args = dict(time_width=0.2, freq_width=10, keep_tapers=True)
        if method != 'coherence': spec_args.update(spacing=1/smp_rate)
    else:
        spec_args = {}

    lfpspec, freqs, timepts = spectrogram(lfpdata, smp_rate, axis=1, method=spec_method,
                                          spec_type='complex', **spec_args)

    # Must convert spike data to spectral for coherence
    if method == 'coherence':
        spkspec, _, _ = spectrogram(spkdata, smp_rate, axis=1, method=spec_method,
                                    spec_type='complex', **spec_args)
    # Must insert singleton axis to match freq axis for other methods
    else:
        spkspec = spkdata[:,np.newaxis,np.newaxis,:] if spec_method == 'multitaper' \
                  else spkdata[:,np.newaxis,:]
    n_new_axes = 2 if spec_method == 'multitaper' else 1
    time_axis = 1 + n_new_axes

    if (spec_method == 'multitaper') and (method != 'coherence'):
        timepts_raw = np.arange(0,lfpdata.shape[1])/smp_rate
        retained_times = (timepts_raw >= timepts[0]) & (timepts_raw <= timepts[-1])
        spkspec = index_axis(spkspec, time_axis, retained_times)
        extra_args.update(timepts=extra_args['timepts'][retained_times], taper_axis=time_axis-1)
    elif spec_method == 'multitaper':
        extra_args.update(timepts=timepts, taper_axis=time_axis-1, width=0.2)

    # if spec_method == 'multitaper': extra_args.update(taper_axis=time_axis-1,timepts=timepts[retained_times])
    sync, _, _, n, phi = spike_field_coupling(spkspec, lfpspec, axis=0, time_axis=time_axis,
                                              method=method, spec_method=spec_method,
                                              return_phase=True, **extra_args)
    assert np.array_equal(spkdata,spkdata_orig)     # Ensure input data isn't altered by function
    assert np.array_equal(lfpdata,lfpdata_orig)
    assert sync.shape == (n_freqs, n_timepts)
    assert phi.shape == (n_freqs, n_timepts)
    assert np.issubdtype(sync.dtype,float)
    assert np.issubdtype(phi.dtype,float)
    assert np.isclose(np.nanmean(sync), result[0], rtol=1e-4, atol=1e-4)
    assert np.isclose(np.nanmean(phi), result[1], rtol=1e-4, atol=1e-4)
    if method != 'coherence': assert np.round(n.mean()) == result[2]

    # Ensure that passing a nonexistent/misspelled kwarg raises an error
    with pytest.raises((TypeError,AssertionError)):
        sync, freqs, timepts, n, phi = spike_field_coupling(spkdata, lfpdata, axis=0, time_axis=-1,
                                                            method=method, spec_method=spec_method,
                                                            smp_rate=smp_rate, return_phase=True,
                                                            foo=None, **extra_args)