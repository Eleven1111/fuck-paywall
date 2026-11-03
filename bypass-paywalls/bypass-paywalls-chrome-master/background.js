'use strict';

var defaultSites = {
  'Baltimore Sun': 'baltimoresun.com',
  'Barron\'s': 'barrons.com',
  'Bloomberg': 'bloomberg.com',
  'Crain\'s Chicago Business': 'chicagobusiness.com',
  'Chicago Tribune': 'chicagotribune.com',
  'Corriere Della Sera': 'corriere.it',
  'Daily Press': 'dailypress.com',
  'Dagens Nyheter': 'dn.se',
  'Denver Post': 'denverpost.com',
  'Dynamed Plus': 'dynamed.com',
  'The Economist': 'economist.com',
  'Les Echos': 'lesechos.fr',
  'Encyclopedia Britannica': 'britannica.com',
  'Examiner': 'examiner.com.au',
  'Financial Times': 'ft.com',
  'Foreign Policy': 'foreignpolicy.com',
  'Glassdoor': 'glassdoor.com',
  'Haaretz': 'haaretz.co.il',
  'Haaretz English': 'haaretz.com',
  'Hartford Courant': 'courant.com',
  'Harper\'s Magazine': 'harpers.org',
  'Harvard Business Review': 'hbr.org',
  'Inc.com': 'inc.com',
  'Irish Times': 'irishtimes.com',
  'La Repubblica': 'repubblica.it',
  'Liberation': 'liberation.fr',
  'Los Angeles Times': 'latimes.com',
  'Medium': 'medium.com',
  'MIT Technology Review': 'technologyreview.com',
  'Newsrep': 'thenewsrep.com',
  'Nikkei Asian Review': 'asia.nikkei.com',
  'NRC': 'nrc.nl',
  'OrlandoSentinel': 'orlandosentinel.com',
  'Quora': 'quora.com',
  'SunSentinel': 'sun-sentinel.com',
  'The Advocate': 'theadvocate.com.au',
  'The Age': 'theage.com.au',
  'The Boston Globe': 'bostonglobe.com',
  'The Japan Times': 'japantimes.co.jp',
  'TheMarker': 'themarker.com',
  'The Mercury News': 'mercurynews.com',
  'The Morning Call': 'mcall.com',
  'The Nation': 'thenation.com',
  'The New Statesman': 'newstatesman.com',
  'The New York Times': 'nytimes.com',
  'The New Yorker': 'newyorker.com',
  'The Seattle Times': 'seattletimes.com',
  'The Spectator': 'spectator.co.uk',
  'The Sydney Morning Herald': 'smh.com.au',
  'The Washington Post': 'washingtonpost.com',
  'The Wall Street Journal': 'wsj.com',
  'Winston-Salem Journal': 'journalnow.com',
  'Wired': 'wired.com'
};

const restrictions = {
  'barrons.com': 'barrons.com/articles'
}

// Don't remove cookies before page load
const allow_cookies = [
'asia.nikkei.com',
'nytimes.com',
'wsj.com',
'ft.com',
'fd.nl',
'mercurynews.com',
'theage.com.au',
'economist.com',
'bostonglobe.com',
'denverpost.com',
'chicagobusiness.com',
'theadvocate.com.au',
'examiner.com.au',
'hbr.org',
'medium.com',
'washingtonpost.com',
]

// Removes cookies after page load
const remove_cookies = [
'asia.nikkei.com',
'ft.com',
'fd.nl',
'mercurynews.com',
'theage.com.au',
'economist.com',
'bostonglobe.com',
'wired.com',
'denverpost.com',
'chicagobusiness.com',
'harpers.org',
'theadvocate.com.au',
'examiner.com.au',
'lesechos.fr',
'liberation.fr',
'hbr.org',
'medium.com',
'foreignpolicy.com',
'wsj.com',
'seattletimes.com',
'thenewsrep.com',
'washingtonpost.com',
]


// Requests to these hosts are blocked when they come from (or go to) an enabled site.
// MV2 used regexes on the request URL; MV3 uses declarativeNetRequest block rules.
const blockedRequests = [
  // Tribune Publishing paywall scripts, loaded by the Tribune papers
  { urlFilter: '||tribdss.com/', initiatorSites: ['baltimoresun.com', 'chicagotribune.com', 'courant.com', 'dailypress.com', 'latimes.com', 'mcall.com', 'orlandosentinel.com', 'sun-sentinel.com'] },
  { regexFilter: 'thenation\\.com/.+/paywall-script\\.php', site: 'thenation.com' },
  { regexFilter: 'haaretz\\.co\\.il/htz/js/inter\\.js', site: 'haaretz.co.il' }
];

// Sites that get Facebook as the referer instead of Google
const facebookReferer = ['wsj.com', 'ft.com'];

const ALL_RESOURCE_TYPES = [
  'main_frame', 'sub_frame', 'stylesheet', 'script', 'image', 'font', 'object',
  'xmlhttprequest', 'ping', 'csp_report', 'media', 'websocket', 'webtransport',
  'webbundle', 'other'
];

// Rule priorities: header rules must outrank the WSJ "allow" rule, which in turn
// outranks the WSJ redirect (so an URL that already has mod=rsswn is not redirected again).
const PRIORITY_HEADERS = 3;
const PRIORITY_ALLOW = 2;
const PRIORITY_DEFAULT = 1;

const CONTENT_SCRIPT_ID = 'bypass-paywalls-content';

function setDefaultOptions() {
  chrome.storage.sync.set({
    sites: defaultSites
  }, function() {
    chrome.runtime.openOptionsPage();
  });
}

function getEnabledSites() {
  return new Promise(function(resolve) {
    chrome.storage.sync.get({ sites: {} }, function(items) {
      resolve(Object.keys(items.sites).map(function(key) {
        return items.sites[key];
      }));
    });
  });
}

// Build the declarativeNetRequest condition that matches requests to an enabled site
function siteCondition(site) {
  if (site in restrictions) {
    return { urlFilter: '||' + restrictions[site], resourceTypes: ALL_RESOURCE_TYPES };
  }
  return { requestDomains: [site], resourceTypes: ALL_RESOURCE_TYPES };
}

function buildRules(enabledSites) {
  var rules = [];
  var id = 1;

  enabledSites.forEach(function(site) {
    // Set referer to Google (or Facebook), and strip cookies unless the site needs them
    var requestHeaders = [{
      header: 'referer',
      operation: 'set',
      value: facebookReferer.includes(site) ? 'https://www.facebook.com/' : 'https://www.google.com/'
    }];
    if (!allow_cookies.includes(site)) {
      requestHeaders.push({ header: 'cookie', operation: 'remove' });
    }
    rules.push({
      id: id++,
      priority: PRIORITY_HEADERS,
      action: { type: 'modifyHeaders', requestHeaders: requestHeaders },
      condition: siteCondition(site)
    });
  });

  blockedRequests.forEach(function(blocked) {
    var condition = { resourceTypes: ALL_RESOURCE_TYPES };
    if (blocked.urlFilter) {
      condition.urlFilter = blocked.urlFilter;
    } else {
      condition.regexFilter = blocked.regexFilter;
    }
    if (blocked.initiatorSites) {
      var initiators = blocked.initiatorSites.filter(function(site) {
        return enabledSites.includes(site);
      });
      if (!initiators.length) {
        return;
      }
      condition.initiatorDomains = initiators;
    } else if (!enabledSites.includes(blocked.site)) {
      return;
    }
    rules.push({ id: id++, priority: PRIORITY_DEFAULT, action: { type: 'block' }, condition: condition });
  });

  // WSJ bypass: add mod=rsswn to article URLs
  if (enabledSites.includes('wsj.com')) {
    rules.push({
      id: id++,
      priority: PRIORITY_ALLOW,
      action: { type: 'allow' },
      condition: { urlFilter: 'mod=rsswn', requestDomains: ['wsj.com'], resourceTypes: ['main_frame'] }
    });
    rules.push({
      id: id++,
      priority: PRIORITY_DEFAULT,
      action: {
        type: 'redirect',
        redirect: { transform: { fragment: '', queryTransform: { addOrReplaceParams: [{ key: 'mod', value: 'rsswn' }] } } }
      },
      condition: { requestDomains: ['wsj.com'], resourceTypes: ['main_frame'] }
    });
  }

  return rules;
}

// Content script (clears localStorage etc.) only runs on enabled sites
function buildContentScriptMatches(enabledSites) {
  var matches = [];
  enabledSites.forEach(function(site) {
    var path = '/*';
    var host = site;
    if (site in restrictions) {
      var restriction = restrictions[site];
      host = restriction.split('/')[0];
      path = restriction.substring(host.length) + '*';
    }
    matches.push('*://' + host + path, '*://*.' + host + path);
  });
  return matches;
}

async function syncRules() {
  var enabledSites = await getEnabledSites();

  var oldRules = await chrome.declarativeNetRequest.getDynamicRules();
  await chrome.declarativeNetRequest.updateDynamicRules({
    removeRuleIds: oldRules.map(function(rule) { return rule.id; }),
    addRules: buildRules(enabledSites)
  });

  var registered = await chrome.scripting.getRegisteredContentScripts({ ids: [CONTENT_SCRIPT_ID] });
  if (registered.length) {
    await chrome.scripting.unregisterContentScripts({ ids: [CONTENT_SCRIPT_ID] });
  }
  var matches = buildContentScriptMatches(enabledSites);
  if (matches.length) {
    await chrome.scripting.registerContentScripts([{
      id: CONTENT_SCRIPT_ID,
      js: ['contentScript.js'],
      matches: matches,
      runAt: 'document_start'
    }]);
  }
}

// Serialize syncs so overlapping storage changes don't race each other
var syncQueue = Promise.resolve();
function queueSync() {
  syncQueue = syncQueue.then(syncRules).catch(function(err) {
    console.error('Failed to update rules:', err);
  });
  return syncQueue;
}

// Listen for changes to options
chrome.storage.onChanged.addListener(function(changes, namespace) {
  if ('sites' in changes) {
    queueSync();
  }
});

// Set and show default options on install
chrome.runtime.onInstalled.addListener(function (details) {
  if (details.reason == "install") {
    setDefaultOptions();
  } else {
    // Extension updated (e.g. from the MV2 version): rebuild rules from saved options
    queueSync();
  }
});

chrome.runtime.onStartup.addListener(queueSync);

// remove cookies after page load
chrome.webRequest.onCompleted.addListener(async function(details) {
  var enabledSites = await getEnabledSites();
  remove_cookies.forEach(function(domainVar) {
    if (!enabledSites.includes(domainVar) || details.url.indexOf(domainVar) === -1) {
      return; // don't remove cookies
    }
    chrome.cookies.getAll({domain: domainVar}, function(cookies) {
      for (var i=0; i<cookies.length; i++) {
        chrome.cookies.remove({url: (cookies[i].secure ? "https://" : "http://") + cookies[i].domain.replace(/^\./, "") + cookies[i].path, name: cookies[i].name});
      }
    });
  });
}, {
  urls: ["<all_urls>"]
});
