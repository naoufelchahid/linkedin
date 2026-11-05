"""Validation des dossiers et invariants indépendants du modèle."""
import hashlib
import json
import re
import unicodedata
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def fingerprint(payload, cv_hash):
    return hashlib.sha256((canonical_json(payload) + cv_hash).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(text):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', text.casefold())
                           if not unicodedata.combining(c)).split())


# Ne pas transmettre de montant ni de discussion de rémunération dans les cartes/réponses.
MONEY = re.compile(r'(?i)\b(?:tarifs?|tjm|salaire|salary|salaries|remuneration|rémunération|'
                   r'pretentions salariales|prétentions salariales|daily rate|hourly rate|'
                   r'MAD|DH|DHS|EUR|USD|dirhams?|euros?|dollars?)\b|[€$£]')


def safe_content(value):
    return not MONEY.search(canonical_json(value))


def public_url(url):
    """Accepter seulement une destination HTTPS publique, sans identifiants intégrés."""
    p = urlparse(url)
    host = p.hostname or ''
    if p.scheme != 'https' or p.username or p.password or not host or '.' not in host:
        raise ValueError('destination_invalid')
    import ipaddress
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if host.endswith(('.local', '.localhost', '.internal')):
            raise ValueError('destination_invalid')
    else:
        if not ip.is_global:
            raise ValueError('destination_invalid')
    return url


def dedupe_key(payload):
    # Une référence employeur commune prime lorsqu'elle est explicitement observée.
    reference = payload.get('employer_reference', '')
    fields = [payload['company'], reference] if reference else [
        payload['company'], payload['title'], payload['location']]
    return hashlib.sha256(normalize('|'.join(fields)).encode()).hexdigest()


def canonical_apply_url(url):
    p = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith('utm_')
             and k.lower() not in {'trk', 'trackingid', 'ref', 'refid', 'source'}]
    return urlunparse((p.scheme, p.netloc.lower(), p.path.rstrip('/'), '', urlencode(sorted(query)), ''))


def validate_candidate(p, *, allow_freelance_proposal=False):
    required = ['job_id', 'title', 'company', 'location', 'job_url', 'apply_url',
                'contract', 'work_mode', 'summary', 'response_summary', 'fit_evidence',
                'gaps', 'answers', 'letter', 'blockers', 'form_complete', 'employer_reference']
    if any(k not in p for k in required):
        raise ValueError('missing_fields')
    if not re.fullmatch(r'\d{5,20}', p['job_id']):
        raise ValueError('invalid_job_id')
    if p['job_url'] != f"https://www.linkedin.com/jobs/view/{p['job_id']}/":
        raise ValueError('invalid_job_url')
    public_url(p['apply_url'])
    if p['contract'] not in {'freelance', 'uncertain'}:
        raise ValueError('not_freelance')
    if re.search(r'(?i)\b(?:CDI|CDD|internship|stage)\b', p['title']):
        raise ValueError('salaried_or_internship')
    if not p['fit_evidence'] or not p['summary'] or not p['response_summary']:
        raise ValueError('missing_evidence')
    if not isinstance(p['form_complete'], bool):
        raise ValueError('invalid_form_status')
    if not safe_content(p):
        raise ValueError('excluded_content')
    for answer in p['answers']:
        if not all(answer.get(k) for k in ('question', 'answer', 'source')):
            raise ValueError('unsubstantiated_answer')
    if p['contract'] == 'uncertain' and not p['blockers'] and not allow_freelance_proposal:
        p['blockers'] = ['Nature freelance du contrat à confirmer.']
    if not p['form_complete'] and not p['blockers']:
        p['blockers'] = ['Lecture complète du formulaire requise avant soumission.']
    return p
