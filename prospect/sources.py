"""Bounded, public, read-only discovery. A search result is never a verified opportunity."""
from __future__ import annotations
import datetime as dt
import hashlib
import ipaddress
import json
import os
import re
import socket
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from html.parser import HTMLParser

MAX_BYTES = 1_500_000
USER_AGENT = "Prospect/0.1 (local read-only project discovery)"


class ForumListing(HTMLParser):
    """Public listing titles only; never treats forum authors as verified officials."""
    def __init__(self):super().__init__(convert_charrefs=True);self.entries=[];self.anchor=None
    def handle_starttag(self,tag,attrs):
        if tag=='a':self.anchor=[dict(attrs).get('href',''),[]]
    def handle_data(self,text):
        if self.anchor is not None:self.anchor[1].append(text)
    def handle_endtag(self,tag):
        if tag=='a' and self.anchor is not None:
            self.entries.append((self.anchor[0],' '.join(''.join(self.anchor[1]).split())));self.anchor=None


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def defaults():
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).date().isoformat()
    def search(query):
        return "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
            {"q": query + " pushed:>=" + since, "sort": "updated", "order": "desc", "per_page": 10})
    return [
        {"id": "github-pow", "label": "GitHub · 挖矿代码线索", "url": search("mining cryptocurrency"),
         "kind": "github", "category": "pow", "enabled": True, "interval_seconds": 1800},
        {"id": "github-nodes", "label": "GitHub · 测试网节点线索", "url": search("testnet node"),
         "kind": "github", "category": "node", "enabled": True, "interval_seconds": 1800},
        {"id": "github-tasks", "label": "GitHub · 测试网任务线索", "url": search("airdrop testnet"),
         "kind": "github", "category": "tasks", "enabled": True, "interval_seconds": 1800},
        {"id": "ethereum-releases", "label": "Ethereum · 官方协议更新（观察源）",
         "url": "https://github.com/ethereum/consensus-specs/releases.atom", "kind": "atom",
         "category": "node", "enabled": False, "interval_seconds": 3600,
         "note": "已知主网项目的技术更新源；不作为未开盘项目推荐。"},
    ]


def validate_public_url(url: str, resolve=True):
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None, 443):
        raise ValueError("Only public HTTPS sources on port 443 are allowed")
    if p.hostname.lower() in ("localhost", "localhost.localdomain") or p.hostname.endswith(".local"):
        raise ValueError("Local sources are forbidden")
    try:
        literal = ipaddress.ip_address(p.hostname)
    except ValueError:
        literal = None
    if literal and not literal.is_global:
        raise ValueError("Private or reserved source address")
    if resolve:
        addresses = socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError("Source resolved to a non-public address")
    return p


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_url(newurl)
        # Discovery presets are fixed public sources. Do not follow to another origin.
        if urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(req.full_url).hostname:
            raise ValueError("Cross-origin redirects require an explicit source review")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def source_proxies():
    """NO_PROXY alone must not mask existing Windows scheme proxy settings."""
    proxies=urllib.request.getproxies().copy()
    if os.name=='nt':
        environment={key.lower():value for key,value in os.environ.items() if key.lower().endswith('_proxy')}
        registry=urllib.request.getproxies_registry()
        for scheme in ('http','https'):
            if scheme in proxies or scheme+'_proxy' in environment:continue
            if proxies.get('all'):proxies[scheme]=proxies['all']
            elif registry.get(scheme):proxies[scheme]=registry[scheme]
    return proxies


def fetch(source: dict, health: dict) -> tuple[int, dict, bytes]:
    validate_public_url(source["url"])
    accept='application/vnd.github+json' if source['kind']=='github' else 'text/html' if source['kind']=='launch_page' else 'application/rss+xml, application/atom+xml'
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    for old, new in (("etag", "If-None-Match"), ("last_modified", "If-Modified-Since")):
        if health.get(old): headers[new] = health[old]
    req = urllib.request.Request(source["url"], headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(source_proxies()),PublicRedirect())
    try:
        with opener.open(req, timeout=15) as response:
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES: raise ValueError("Source response exceeds size limit")
            return response.status, dict(response.headers.items()), body
    except urllib.error.HTTPError as exc:
        if exc.code == 304: return 304, dict(exc.headers.items()), b""
        if exc.code in (403, 429): raise ValueError("Source rate limited; retry after the configured interval") from None
        raise ValueError(f"Source HTTP {exc.code}") from None


def parse(source: dict, body: bytes) -> list[dict]:
    from .launch_watch import infer,plain,canonical_announcement
    timestamp = now()
    items = []
    if source['kind']=='launch_forum':
        if urllib.parse.urlsplit(source['url']).hostname!='bitcointalk.org':raise ValueError('Unreviewed forum host')
        listing=ForumListing();listing.feed(body.decode('utf-8','replace'));topics={}
        for href,title in listing.entries:
            url=urllib.parse.urljoin(source['url'],href);parts=urllib.parse.urlsplit(url)
            if parts.hostname!='bitcointalk.org' or 'topic' not in urllib.parse.parse_qs(parts.query) or len(title)<8:continue
            try:url=canonical_announcement(url)
            except ValueError:continue
            topics.setdefault(url,title)
        if not topics:raise ValueError('Forum page did not contain public topic titles; coverage unavailable')
        for url,title in list(topics.items())[:80]:
            if not re.search(r'\b(?:mining|miner|mined|mineable|pow|randomx|cpu|gpu|sha[ -]?256|proof.of.work)\b|挖矿|开挖|矿币',title,re.I):continue
            signal=infer(title,url,'community')
            category='node' if re.search(r'\brendering\b|\bcompute contribution\b',title,re.I) and not re.search(r'\bmining\b|\bpow\b',title,re.I) else 'pow'
            item={'identity_key':'announcement:'+url,'name':title[:150],'category':category,'url':url,'summary':title[:1200],
                'requirements':{},'market':{},'participation':'unknown','checked_at':timestamp,
                'evidence':[{'url':url,'kind':'discovery','note':'公开论坛公告标题；正文、作者与官方身份、主网窗口尚未核实。','checked_at':timestamp}]}
            if signal:item['launch_signal']=signal
            items.append(item)
    elif source['kind'] in ('launch_rss','launch_page'):
        if source['kind']=='launch_page':
            entries=[(source['project_name'],source['url'],body.decode('utf-8','replace'))]
        else:
            tree=ET.fromstring(body);entries=[]
            for entry in tree.findall('.//item')[:30]:
                entries.append((entry.findtext('title',''),entry.findtext('link',''),entry.findtext('description','')))
            if not entries:
                ns={'a':'http://www.w3.org/2005/Atom'}
                for entry in tree.findall('a:entry',ns)[:30]:
                    link=entry.find('a:link',ns)
                    entries.append((entry.findtext('a:title','',ns),link.get('href','') if link is not None else '',entry.findtext('a:content','',ns) or entry.findtext('a:summary','',ns)))
        for title,url,content in entries:
            try:url=canonical_announcement(url)
            except ValueError:continue
            signal=infer(title+'\n'+content,url,source.get('evidence_kind','community'))
            if signal:
                items.append({'identity_key':source.get('project_identity','announcement:'+url),'name':title[:150] or '开挖预告',
                    'category':'pow','url':url,'summary':plain(content)[:1200],'requirements':{},'market':{},'checked_at':timestamp,
                    'evidence':[{'url':url,'kind':'primary' if signal['evidence_kind']=='primary' else 'discovery',
                        'note':signal['evidence_note'],'checked_at':timestamp}],'launch_signal':signal})
    elif source["kind"] == "github":
        payload = json.loads(body)
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise ValueError("Unexpected GitHub response schema")
        for repo in payload["items"][:20]:
            url = repo.get("html_url", "")
            validate_public_url(url, resolve=False)
            if urllib.parse.urlsplit(url).hostname != "github.com": continue
            signal=infer(repo['full_name']+' '+(repo.get('description') or ''),url) if source.get('launch_discovery') else None
            if source.get('launch_discovery') and not signal:continue
            items.append({"id": "gh-" + str(repo["id"]), "identity_key": "github:" + repo["full_name"].lower(),
                          "name": repo["full_name"], "category": source["category"], "url": url,
                          "summary": (repo.get("description") or "暂无项目说明")[:1200],
                          "requirements": {}, "market": {}, "participation": "unknown", "reward_unit": "unknown",
                          "checked_at": timestamp,
                          "evidence": [{"url": url, "kind": "discovery", "note": "仓库搜索命中；作者身份、奖励、可参与性与交易状态均待核验。", "checked_at": timestamp}],
                          **({'launch_signal':signal} if signal else {})})
    elif source["kind"] == "atom":
        tree = ET.fromstring(body)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in tree.findall("a:entry", ns)[:10]:
            link = entry.find("a:link", ns)
            url = link.get("href", "") if link is not None else ""
            validate_public_url(url, resolve=False)
            title = entry.findtext("a:title", default="Release", namespaces=ns)
            items.append({"identity_key": "release:" + url, "name": title[:120], "category": source["category"], "url": url,
                          "summary": "官方技术更新，不代表新的未开盘机会。", "requirements": {},
                          "market": {"cex_spot": "yes", "dex_spot": "yes"} if source["id"] == "ethereum-releases" else {},
                          "participation": "unknown", "reward_unit": "unknown", "checked_at": timestamp,
                          "evidence": [{"url": url, "kind": "official", "note": "协议发布记录；不能据此推断奖励。", "checked_at": timestamp}]})
    else:
        raise ValueError("Unsupported connector")
    return items


def scan(store, fetcher=fetch, force=False):
    from .launch_watch import LaunchWatch
    watch=LaunchWatch(store)
    sources = store.get_setting("sources", defaults())
    health = store.get_setting("source_health", {})
    counts = {"checked": 0, "changed": 0, "items": 0, "errors": 0, "unchanged": 0, "skipped": 0}
    for source in sources:
        if not source.get("enabled"): continue
        old = health.get(source["id"], {})
        due = float(old.get("next_check_epoch", 0))
        if due > time.time() and not force:
            counts["skipped"] += 1
            continue
        started = time.monotonic()
        at = now()
        counts["checked"] += 1
        result = {"source_id": source["id"], "at": at, "count": 0, "changed": 0, "status": "ok"}
        new = old | {"last_checked": at, "next_check_epoch": time.time() + max(60, int(source["interval_seconds"]))}
        try:
            status, headers, body = fetcher(source, old)
            lower_headers = {k.lower(): v for k, v in headers.items()}
            if status not in (200, 304):
                raise ValueError(f"Unexpected status {status}")
            if status == 304 and not old.get("content_hash"):
                raise ValueError("304 response without a validated cached representation")
            if status == 200 and not body:
                raise ValueError("Empty source response")
            checksum = hashlib.sha256(body).hexdigest() if status == 200 else old["content_hash"]
            if status == 304 or (old.get("content_hash") and checksum == old["content_hash"]):
                result["status"] = "unchanged"
                counts["unchanged"] += 1
                watch.touch(source['id'])
            elif status == 200:
                items = parse(source, body)
                for item in items:
                    saved = store.upsert_candidate(item)
                    if item.get('launch_signal'):watch.observe(saved['id'],item['launch_signal'],source['id'])
                    result["changed"] += int(saved["changed"])
                result["count"] = len(items)
                counts["items"] += len(items)
                counts["changed"] += result["changed"]
            else:
                raise ValueError(f"Unexpected status {status}")
            new.update(status=result["status"], last_success=at, error=None, content_hash=checksum,
                       failures=0, etag=lower_headers.get("etag", old.get("etag")),
                       last_modified=lower_headers.get("last-modified", old.get("last_modified")))
        except Exception as exc:
            # No response bodies or credentials are included in the error ledger.
            failures = min(8, int(old.get("failures", 0)) + 1)
            error = str(exc)[:220] if isinstance(exc, (ValueError, OSError)) else type(exc).__name__
            new.update(status="error", error=error, failures=failures,
                       next_check_epoch=time.time() + min(21600, source["interval_seconds"] * 2**failures))
            result.update(status="error", error=error)
            counts["errors"] += 1
        result["duration_ms"] = round((time.monotonic() - started) * 1000)
        store.record_scan(result)
        health[source["id"]] = new
        store.set_setting("source_health", health)
    return counts


def import_legacy(store, database: Path) -> dict:
    """Read legacy records without importing its side-effectful Python module."""
    if not database.exists(): return {"imported": 0, "changed": 0, "message": "Legacy database not found"}
    c = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = c.execute("SELECT payload FROM candidates ORDER BY last_seen DESC LIMIT 500").fetchall()
    finally:
        c.close()
    count, changed = 0, 0
    for (raw,) in rows:
        old = json.loads(raw)
        review = old.get("review") or {}
        category = "node" if "node" in review.get("kind", "").lower() else "pow"
        # Legacy prelaunch means not-yet-mining, NOT verified absence of spot markets.
        item = {"identity_key": "legacy:" + old.get("project_key", old["id"]), "name": old.get("project", "Unknown"),
                "url": old.get("url"), "category": category, "summary": review.get("summary") or old.get("text", "")[:1200],
                "requirements": {}, "market": {}, "participation": "closed" if review.get("mining_status") == "closed" else "unknown",
                "reward_unit": "unknown", "checked_at": review.get("checked_at") or now(),
                "evidence": [{"url": e["url"], "kind": "legacy", "note": e.get("note", "历史核验记录，需重新核实"),
                              "checked_at": review.get("checked_at") or now()} for e in old.get("evidence", [])[:12]]}
        try:
            saved = store.upsert_candidate(item)
            count += 1
            changed += int(saved["changed"])
        except ValueError:
            continue
    return {"imported": count, "changed": changed, "source": str(database), "mode": "read_only"}
