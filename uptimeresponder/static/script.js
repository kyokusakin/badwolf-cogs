let serverStartTime, lastUpdateTime, uptimeInterval, statusInterval;

const formatUptime = (uptime) => {
    const { days, hours, minutes, seconds } = uptime;
    const daysText = window.translation && window.translation.days ? window.translation.days : 'days';

    if (days > 0) {
        return `${days} ${daysText} ${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    } else {
        return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    }
};

const updateUptime = () => {
    const now = Date.now();
    let uptime = Math.floor((now - serverStartTime) / 1000);
    const formattedUptime = parseUptimeSeconds(uptime);
    document.getElementById('uptime').textContent = formatUptime(formattedUptime);
};

const handleStatusResponse = (data) => {
    const serverUptime = parseUptimeString(data.uptime);
    const now = Date.now();

    if (!serverStartTime) {
        serverStartTime = now - serverUptime.totalSeconds * 1000;
    } else {
        const expectedUptime = now - serverStartTime;
        const diff = Math.abs(serverUptime.totalSeconds * 1000 - expectedUptime);
        if (diff > 2000) {
            serverStartTime = now - serverUptime.totalSeconds * 1000;
        }
    }

    const formattedUptime = parseUptimeString(serverUptime.totalSeconds);
    document.getElementById('uptime').textContent = formatUptime(formattedUptime);
    document.getElementById('latency').textContent = `${data.latency} ms`;
    lastUpdateTime = now;

    if (!uptimeInterval) {
        uptimeInterval = setInterval(updateUptime, 1000);
    }
};

const fetchStatus = () => {
    fetch('/status', { method: 'GET' })
        .then(response => {
            if (response.status === 429) {
                document.getElementById('uptime').textContent = 'Rate limited';
                clearInterval(uptimeInterval);
                uptimeInterval = null;

                const retryAfter = response.headers.get('Retry-After');
                if (retryAfter) {
                    console.warn(`Rate limited. Retrying after ${retryAfter} seconds.`);
                    setTimeout(() => {
                        fetchStatus();
                        statusInterval = setInterval(fetchStatus, 10000);
                    }, retryAfter * 1000);
                } else {
                    console.warn('Rate limited. Retrying after 10 seconds.');
                    setTimeout(() => {
                        fetchStatus();
                        statusInterval = setInterval(fetchStatus, 10000);
                    }, 10000);
                }
                clearInterval(statusInterval);
                return Promise.reject('Rate limited');
            }
            if (response.status === 403) {
                alert('Access forbidden. Refreshing page in 3 seconds...');
                setTimeout(() => {
                    location.reload();
                }, 3000);
                return Promise.reject('Access forbidden');
            }
            if (!response.ok) {
                return Promise.reject('Network response was not ok');
            }
            return response.json();
        })
        .then(handleStatusResponse)
        .catch(error => {
            console.error('Error fetching status:', error);
            document.getElementById('latency').textContent = 'Time out';
            if (Date.now() - lastUpdateTime > 30000) {
                document.getElementById('uptime').textContent = 'Time out';
                clearInterval(uptimeInterval);
                uptimeInterval = null;
                serverStartTime = null;
            }
        });
};

const parseUptimeString = (uptimeString) => {
    const totalSeconds = Number(uptimeString);
    const days = Math.floor(totalSeconds / 86400);
    const hours = Math.floor((totalSeconds % 86400) / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;

    return { totalSeconds, days, hours, minutes, seconds };
};

const parseUptimeSeconds = (seconds) => {
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainingSeconds = seconds % 60;

    return { days, hours, minutes, seconds: remainingSeconds };
};

document.addEventListener('DOMContentLoaded', () => {
    fetchStatus();
    statusInterval = setInterval(fetchStatus, 10000);

    // 語言切換時更新天數顯示
    const languageSwitcher = document.querySelector('.language-switcher select');
    languageSwitcher.addEventListener('change', async (event) => {
        const lang = event.target.value;
        const response = await fetch('translations.json');
        const translations = await response.json();
        const translation = translations[lang];
        window.translation = translation; // 更新全局翻譯變量

        // 更新頁面上的文本
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

        // 更新天數顯示
        const uptimeElement = document.getElementById('uptime');
        const uptimeText = uptimeElement.textContent;
        if (uptimeText.includes('days') || uptimeText.includes('天')) {
            const updatedUptimeText = uptimeText.replace(/days|天/, translation.days);
            uptimeElement.textContent = updatedUptimeText;
        }
    });
});
