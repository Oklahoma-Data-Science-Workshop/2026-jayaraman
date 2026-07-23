import re
import requests
import logging

log = logging.getLogger(__name__)

ILAB_BASE = 'https://my.ilabsolutions.com'

CORES = {
    'Tissue Pathology Core': {
        'core_id': 3205,
        'equipment': {
            '472362': 'Axioscan Zeiss Slide Scanner',
            '447794': 'Cryostat Frozen Tissue Sectioning',
            '488844': 'HALO Laptop 1',
            '489988': 'HALO Laptop 2',
            '492918': 'HALO Laptop 3',
            '531822': 'TMA Grandmaster',
            '464323': 'BRC1471 Room Access',
            '482282': 'Leica Multistainer',
            '406044': 'Cytospin V4',
            '253565': 'Nikon Microscope Imaging',
            '509039': 'Leica FFPE Microtome',
        }
    },
    'Functional Genomics Core': {
        'core_id': 3202,
        'equipment': {
            '251168': 'Biorad CFX96 Touch Real-Time PCR',
            '251169': 'Perkin Elmer EnVision Multilabel Reader',
            '251562': 'XF Analyzer',
            '345622': 'Beckman Ultracentrifuge',
            '287989': 'Optronix GelCount Colony Counter',
            '297650': 'iBright FL1500 Imaging System',
            '252933': 'Perkin Elmer Operetta',
            '251285': 'Agilent 2100 Bioanalyzer',
            '297940': 'GenePix 4100A Microarray Scanner',
            '251170': 'Biorad Experion Electrophoresis',
            '252932': 'BioRad PCR Machine',
            '465989': 'Nikon Microscope',
            '406041': 'Olympus Inverted Microscope',
            '488843': 'EVOS M7000 Imaging System',
            '464703': 'BRC1416 Room',
            '516975': 'Incucyte S3 Live Cell Imaging',
            '251171': 'Janus Automated Workstation',
            '251167': 'Agilent SureScan Microarray Scanner',
            '381595': 'FlowJo Software',
        }
    }
}


class ILabClient:
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)',
            'Accept': 'application/json, text/html, */*',
        })
        self._logged_in = False

    def login(self):
        r = self.session.get(f'{ILAB_BASE}/account/login', timeout=30)
        r.raise_for_status()

        # Extract CSRF token (Rails/Devise format — two common placements)
        m = (re.search(r'<meta[^>]+name="csrf-token"[^>]+content="([^"]+)"', r.text)
             or re.search(r'name="authenticity_token"[^>]+value="([^"]+)"', r.text)
             or re.search(r'value="([^"]+)"[^>]+name="authenticity_token"', r.text))
        token = m.group(1) if m else ''

        payload = {'login': self.username, 'password': self.password}
        if token:
            payload['authenticity_token'] = token

        r = self.session.post(f'{ILAB_BASE}/account/login', data=payload,
                              allow_redirects=True, timeout=30)

        self._logged_in = (
            'logout' in r.text.lower()
            or 'sign out' in r.text.lower()
            or 'sign_out' in r.text.lower()
            or r.url != f'{ILAB_BASE}/account/login'
        )
        if not self._logged_in:
            raise RuntimeError('iLab login failed — check ILAB_USERNAME / ILAB_PASSWORD in .env')
        log.info('iLab login successful')

    def _get_json(self, url, params):
        r = self.session.get(url, params=params, timeout=30)
        if r.status_code in (302, 401) or '/login' in r.url:
            log.info('Session expired — re-authenticating')
            self.login()
            r = self.session.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def get_reservations(self, schedule_id, from_date, to_date):
        url = f'{ILAB_BASE}/schedules/{schedule_id}/service_reservations.json'
        params = {'from': from_date, 'to': to_date, 'timeshift': 300, 'pp': 'skip'}
        data = self._get_json(url, params)
        return data.get('reservations', [])

    def fetch_all(self, from_date, to_date):
        results = []
        for core_name, core_data in CORES.items():
            for sched_id, eq_name in core_data['equipment'].items():
                try:
                    rsvs = self.get_reservations(sched_id, from_date, to_date)
                    for res in rsvs:
                        res['_core_name'] = core_name
                        res['_eq_name'] = eq_name
                        res['_schedule_id'] = sched_id
                    results.extend(rsvs)
                    log.debug('%s: %d reservations', eq_name, len(rsvs))
                except Exception as e:
                    log.warning('Error fetching %s (schedule %s): %s', eq_name, sched_id, e)
        return results
