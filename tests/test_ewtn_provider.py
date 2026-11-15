from __future__ import annotations

from epgforgearr.providers.ewtn import EwtnProvider, _ScheduleParser


def test_ewtn_schedule_parser_extracts_programme_fields_and_ignores_other_list_items():
    parser = _ScheduleParser()
    parser.feed('''<ul><li class="cd-program-spot"><div class="cd-spot-start">23:30 Uhr</div>
    <h3 class="cd-spot-title">Sendung A</h3><h4 class="cd-spot-sub-title">Untertitel</h4>
    <p><span class="cd-spot-description-short">Kurzinfo</span><span class="cd-spot-description-long">Langinfo</span></p></li>
    <li class="cd-program-spot"><div class="cd-spot-start">00:15 Uhr</div><h3 class="cd-spot-title">Sendung B</h3></li>
    <li>not a programme</li></ul>''')
    assert parser.programmes == [
        {"start": "23:30 Uhr", "title": "Sendung A", "subtitle": "Untertitel", "description": "Kurzinfo"},
        {"start": "00:15 Uhr", "title": "Sendung B"},
    ]


def test_ewtn_channel_id_and_days_bound():
    provider = EwtnProvider()
    assert provider.list_channels() == [{"id": "EWTN.de", "name": "EWTN Deutschland"}]
    assert provider.MAX_DAYS == 7
