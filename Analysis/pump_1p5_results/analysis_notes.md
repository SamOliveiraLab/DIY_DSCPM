# DSCPM positional-mode video characterization — 1.5 µL/min

## Source and calibration

- Source: `DSCPM_1_5_ulpm_jun30.mov`, 18,242 decoded frames, 304.343 seconds.
- Working measurement method: front position of dyed fluid in horizontal tubing (no flow sensor).
- Tube inner diameter: 0.254 mm (radius 0.127 mm); physical width of full video: 150 mm (assumed correct by author).
- Color-front tracker independently checked against the original PIL grayscale-blur edge detector on 570 frames; median absolute difference 1.0 px; 95th percentile 2.0 px.
- Original published notebook printed a 1.4886 µL/min mean for this video; this reanalysis estimates a linear-trend mean of 1.4865 µL/min over 20–280 s.

## Main findings

- Programmed flow: 1.500 µL/min.
- Full movie (0–304.3 s) endpoint-derived mean: 1.4981 µL/min (-0.13% relative error).
- Central interval (20–280 s) endpoint-derived mean: 1.5085 µL/min (+0.57% relative error).
- Central interval (20–280 s) linear-fit trend: 1.4865 µL/min (-0.90% relative error). These estimators differ because of transient behavior and nonconstant slope, so specify the estimator in any manuscript claim.
- Dominant flow-fluctuation frequency: 0.3538 Hz (period 2.83 s), close to the calculated 2.84-second minimum-step interval.
- **Full 20–280 s window statistics (including suspected handoff):** 1-s CV 43.3%; 10-s CV 17.5%; 60-s CV 6.9%. These are within-run temporal CVs, not inter-run reproducibility.
- **Before suspected handoff (20–150 s):** 1-s CV 19.0%, 10-s CV 5.3%, window-mean rate 1.577 µL/min.
- **After suspected handoff (180–280 s):** 1-s CV 23.6%, 10-s CV 6.1%, window-mean rate 1.461 µL/min.

## Candidate syringe-handoff transient

- Around 158.5–159.0 s the dyed front moved forward by approximately 0.151 µL.
- During 159–165 s the net change was approximately 0.0022 µL, equivalent to 0.022 µL/min, i.e., little movement at the optical measurement resolution.
- The shape is consistent with a syringe exchange but **cannot be confirmed as such without motor/valve event logs**. We should show this transient explicitly and avoid claiming strictly uninterrupted instantaneous flow.

## Interpretation and limitations

- The method gives the movement of a dyed liquid front in the measurement tubing, not a direct flow sensor output inside a loaded biological device.
- The 60-fps numerical derivative is noisy and pixel-quantized. Pulsatility metrics therefore specify their flow averaging window, and reported extrema cannot be interpreted as true millisecond-scale peak flow.
- This is **one video/run**, not three independent replicates; temporal windows are correlated and cannot establish inter-run precision.
- The 150 mm field-of-view calibration is an author-confirmed assumption. The 0.030-inch inner diameter in the submitted Methods should be corrected to **0.010 inch (0.254 mm)**.
- The probable handoff is shorter than a full five-day run and does not by itself establish repeatability of automatic switching over days.

## Recommended language for the revision

*Continuous operation* should be defined as unattended operation through automated syringe refilling, not constant instantaneous outlet flow. *Positional-mode low-flow delivery* should be described as time-averaged delivery with measurable periodic fluctuations and a characterized switching transient. These results belong with the Methods/SI and revised Figure 6.
