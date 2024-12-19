async function setLanguage(lang) {
    const response = await fetch('translations.json');
    const translations = await response.json();
    const translation = translations[lang];

    document.documentElement.lang = lang;
    document.getElementById('title').innerText = translation.title;
    document.getElementById('online').innerText = translation.botname + translation.online;
    document.getElementById('loaded').innerText = translation.loaded;
    document.getElementById('uptime-label').innerText = translation.uptime;
    document.getElementById('latency-label').innerText = translation.latency;
    document.getElementById('terms').innerText = translation.terms;
    document.getElementById('privacy').innerText = translation.privacy;
    document.getElementById('terms').href = `/${lang}/terms-of-service`;
    document.getElementById('privacy').href = `/${lang}/privacy-policy`;
}
