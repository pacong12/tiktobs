// Live Date & Day update
document.addEventListener('DOMContentLoaded', () => {
    updateDate();
    setInterval(updateDate, 1000);
});

function updateDate() {
    const dayEl = document.getElementById('day-text');
    const dateEl = document.getElementById('date-text');
    if (!dayEl || !dateEl) return;

    const now = new Date();
    const days = ['Minggu', 'Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu'];
    const dayName = days[now.getDay()];

    const dd = String(now.getDate()).padStart(2, '0');
    const mm = String(now.getMonth() + 1).padStart(2, '0');
    const yyyy = now.getFullYear();

    dayEl.textContent = dayName.toUpperCase();
    dateEl.textContent = `${dd}/${mm}/${yyyy}`;
}
