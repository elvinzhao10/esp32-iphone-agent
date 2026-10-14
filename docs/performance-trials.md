# iPhone input trials — 14 October 2026

The largest measured improvement came from removing unnecessary video settling
waits, then combining independent keyboard actions. Jev adds a small routing cost
when the caller supplies a known screen precondition and a matching saved recipe.
These are focused-field input measurements, not whole-phone task success rates.

## Repeatable task and results

On a Raspberry Pi 3 B+ with the existing ESP32 firmware and live AirPlay mirroring,
replace the visibly focused Spotlight query with `Calendar`. Reset to `Notes`
before each timed attempt. Never press Enter or open a result. Inspect the captured
query and keyboard after execution. Resets and visual inspection are outside the
timed interval. Trial order rotates among direct/edit/workflow paths.

| Path | Trials | Median execution | Visually correct |
| --- | ---: | ---: | ---: |
| Old separate key + type, with two captures | 3 | 3.306 s | 3/3 |
| New separate key + type, with two captures | 3 | 0.374 s | 3/3 |
| New combined edit + capture | 3 | 0.241 s | 3/3 |
| Finite edit workflow, final capture | 3 | 0.271 s | 3/3 |
| Jev selection + saved edit workflow | 3 | 0.407 s | 3/3 |

The comparable separate-call path was about 8.8 times faster. Combining it into an
edit call was about 13.7 times faster than the old two-call path. A workflow has
job-start/polling overhead, so it did not beat a single edit call on this short task.
Use recipes to remove repeated remote decisions and round trips across longer,
known sequences; do not add Jev when the controlling agent already knows which
recipe to run.

Direct/edit/workflow measurements were initiated from the Mac over Tailscale;
Jev measurements ran on the Pi against its Tailscale HTTP address. Jev used a
fresh process with the corrected router module, shared HTTP connection, and the
running server's saved `search-calendar` recipe. Its routing-only median was
135.6 ms (104.0–368.8 ms); confidence was 0.99, eligibility 0.90–0.91 with a 0.90
threshold. Do not interpret the Jev column as a controlled comparison of network
transport overhead. Three samples per path do not establish tail latency.

## Vision provider and router findings

The configured CometAPI `gpt-6-luna` verifier produced an empty reply, a timeout,
then `NO` for a screenshot visibly containing the correct `Calendar` query. The
runner stopped on that negative answer. These model answers are not counted as
verified success. A separate bounded vision-agent attempt failed with HTTP 500
after 8.998 seconds and zero actions; its verifier also returned HTTP 500. There
is no successful full-vision latency comparison from this run.

Initial Jev eligibility calls lacked workflow metadata in the shared state and
escalated despite choosing the correct recipe. TypeSafe questions are isolated,
so both selection and eligibility now receive the catalogue in shared state.
All three corrected calls selected and executed the intended recipe. Jev receives
text context only; it does not inspect screenshots or prove that context is true.

## Physical controls and limits

- Double click selected the Spotlight word; triple click selected the same
  single-word query; a 600 ms hold showed the editing menu. The latter two calls
  took 0.561 and 0.824 seconds without precision aiming. The double click with
  visual aiming took 1.850 seconds. These single observations are not benchmarks.
- Dashboard live keyboard Command-A followed by `Calendar` correctly replaced
  the query without submission; the page reported input completion and no browser
  console errors. Its indicator is request timing, not end-to-end display latency.
- The existing bottom-edge Home swipe failed on this setup. AssistiveTouch's
  visible Home button worked. Search no longer chains a blind Home gesture into
  another swipe; on iPhone the caller must observe Home before invoking Search.
- iPad uses Command-Space/Command-Tab on its device profile. Real iPad hardware,
  paragraph selection, true simultaneous multi-touch, Unicode/IME injection and
  Globe/Fn shortcuts were not validated or added.
- During the trials, Python server RSS was about 62 MiB and UxPlay about 70 MiB;
  available system memory was 485 MiB of 905 MiB. This is one snapshot, not a peak
  memory test. No additional general-purpose agent runtime was installed.

The server was running `f56dabe` during execution measurements; the corrected Jev
module came from `1f0d76d`. Original measurements used `8e27970`.
[Sanitized measurements](input-trials-2026-10-14.json) contain timings and test
metadata. Raw screenshots remain private and are excluded from the repository.
