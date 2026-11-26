"""The dataset schema must only claim what the twin measured."""

import pytest

from service.infrastructure.body import dataset


def _episode(current=-3600.0, curl=-0.18, latency=12.0, spikes=1250, motor=11,
             recruited=885, site=(470.0, 390.0, 950.0)):
    return {"site_um": list(site), "current_na": float(current),
            "source_cell_count": recruited,
            "network": {"spike_count": spikes, "cell_count": 1169},
            "body": {"curl_change_rad": curl, "escape_latency_ms": latency,
                     "motor_spikes": motor, "displacement_mm": 0.7029}}


def test_a_curl_without_the_programme_is_not_an_escape():
    """The curl alone can be produced by walking into an obstacle."""
    signature = dataset.escape_signature(_episode(latency=None))
    assert signature["curled"] is True
    assert signature["programme_fired"] is False
    assert signature["escaped"] is False


def test_the_programme_without_a_curl_is_not_an_escape():
    """A triggered programme that did not move the abdomen did not happen."""
    signature = dataset.escape_signature(_episode(curl=-0.016))
    assert signature["programme_fired"] is True
    assert signature["escaped"] is False


def test_walking_curl_and_escape_curl_are_separated_by_the_threshold():
    walking = dataset.escape_signature(_episode(curl=-0.0162))
    escaping = dataset.escape_signature(_episode(curl=-0.1834))
    assert walking["escaped"] is False
    assert escaping["escaped"] is True


def test_the_label_carries_no_feeling_and_no_per_cell_claim():
    text = str(dataset.label(_episode()))
    for forbidden in ("pain", "nociceptor", "feeling_", "hurt"):
        assert forbidden not in text.replace("not a feeling", "")


def test_motor_spikes_come_from_the_body_block_not_from_every_spike():
    labelled = dataset.label(_episode(spikes=1250, motor=11))
    assert labelled["spike_count"] == 1250
    assert labelled["motor_spikes"] == 11


def test_a_zero_current_is_not_a_noxious_input_and_not_an_error():
    assert dataset.label(_episode(current=0.0))["noxious_input"] is False


def test_the_noxious_label_follows_the_measured_threshold():
    assert dataset.label(_episode(current=-3500.0))["noxious_input"] is False
    assert dataset.label(_episode(current=-3600.0))["noxious_input"] is True
    assert dataset.label(_episode(current=-9600.0))["noxious_input"] is True


def test_the_split_holds_out_a_whole_site():
    records = [_episode(site=(470.0, 390.0, 950.0)),
               _episode(site=(470.0, 390.0, 850.0)),
               _episode(site=(470.0, 390.0, 1000.0))]
    split = dataset.split_by_site(records)
    train_sites = {dataset.site_key(r) for r in split["train"]}
    test_sites = {dataset.site_key(r) for r in split["test"]}
    assert train_sites and test_sites
    assert train_sites.isdisjoint(test_sites)
    assert split["held_out_site"] in test_sites


def test_roc_auc_is_one_half_when_the_score_is_constant():
    assert dataset.roc_auc([1.0, 1.0, 1.0, 1.0], [0, 1, 0, 1]) == pytest.approx(0.5)


def test_roc_auc_is_one_when_every_escape_scores_higher():
    assert dataset.roc_auc([1.0, 2.0, 3.0, 4.0], [0, 0, 1, 1]) == pytest.approx(1.0)


def test_the_dose_baseline_is_reported_next_to_the_network_baseline():
    records = [_episode(current=-2400.0, curl=-0.016, latency=None),
               _episode(current=-4800.0, curl=-0.18, latency=9.0)]
    baseline = dataset.baseline_escape(records)
    assert baseline["episodes"] == 2
    assert baseline["escapes"] == 1
    assert baseline["auc_by_current"] == pytest.approx(1.0)


def test_a_dataset_file_round_trips_with_labels(tmp_path):
    path = tmp_path / "episodes.jsonl"
    written = dataset.write([_episode()], str(path))
    assert written == 1
    text = path.read_text(encoding="utf-8")
    assert "malecns-twin-noxious-dataset-v1" in text
    assert '"escaped": true' in text
