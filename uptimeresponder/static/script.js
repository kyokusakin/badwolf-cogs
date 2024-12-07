let serverStartTime, lastUpdateTime, uptimeInterval, statusInterval;

const formatUptime = (seconds) => {
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainingSeconds = seconds % 60;

    if (days > 0) {
        return `${days}days ${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
    } else {
        return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
    }
};

const updateUptime = () => {
    const now = Date.now();
    const uptime = Math.floor((now - serverStartTime) / 1000); // Convert milliseconds to seconds
    document.getElementById('uptime').textContent = formatUptime(uptime);
};

const handleStatusResponse = (data) => {
    const serverUptime = parseUptimeString(data.uptime); // Convert uptime string to total seconds
    const now = Date.now();

    if (!serverStartTime) {
        serverStartTime = now - serverUptime * 1000; // Convert to milliseconds
    } else {
        const expectedUptime = now - serverStartTime;
        const diff = Math.abs(serverUptime * 1000 - expectedUptime);
        if (diff > 2000) {
            serverStartTime = now - serverUptime * 1000;
        }
    }

    document.getElementById('uptime').textContent = formatUptime(serverUptime);
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

    return { days, hours, minutes, seconds };
};

document.addEventListener('DOMContentLoaded', () => {
    fetchStatus();
    statusInterval = setInterval(fetchStatus, 10000);
});
