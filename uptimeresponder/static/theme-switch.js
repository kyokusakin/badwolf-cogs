function setIframeTheme() {
    var iframe = document.getElementById('status-badge');
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        iframe.src = 'https://bs.status.badwolftw.cloudns.ch/badge?theme=dark';
    } else {
        iframe.src = 'https://bs.status.badwolftw.cloudns.ch/badge?theme=white';
    }
}

setIframeTheme();

window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', setIframeTheme);