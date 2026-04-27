let tg = window.Telegram.WebApp;
tg.expand();
tg.ready();

// Устанавливаем цвета хедера ТГ под стиль сайта
tg.setHeaderColor('#0a0a0c');
tg.setBackgroundColor('#0a0a0c');

let currentGenType = '';
let uploadedBase64 = null;
let userId = tg.initDataUnsafe?.user?.id || 0;

if (tg.initDataUnsafe?.user) {
    document.getElementById('user-name').innerText = tg.initDataUnsafe.user.first_name;
}

// Запрос к Питону
async function apiRequest(endpoint, data) {
    try {
        let response = await fetch(endpoint, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, ...data })
        });
        return await response.json();
    } catch (e) {
        tg.showAlert("Ошибка связи с сервером!"); 
        return { success: false, error: e.message };
    }
}

// Загрузка профиля
async function loadProfile() {
    let res = await apiRequest('/api/profile', {});
    if (res.success) {
        document.getElementById('balance').innerText = res.balance.toFixed(2);
        document.getElementById('sub-status').innerText = res.sub_end ? 'PRO Доступ' : 'Новичок';
    }
}
loadProfile(); // Грузим при старте

// Переключение страниц
function switchTab(tabId) {
    tg.HapticFeedback.impactOccurred('light');
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById(`page-${tabId}`).classList.add('active');

    if (tabId === 'design' || tabId === 'profile') {
        document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
        document.getElementById(`nav-${tabId}`).classList.add('active');
        if (tabId === 'profile') loadProfile();
    }
}

// Обработка загрузки фото
document.getElementById('file-input').addEventListener('change', function(e) {
    if (e.target.files.length > 0) {
        let file = e.target.files[0];
        let reader = new FileReader();
        reader.onload = function(event) {
            uploadedBase64 = event.target.result.split(',')[1];
            document.getElementById('file-label').classList.add('active');
            document.getElementById('file-label').innerHTML = `
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>
                <span style="margin-top:8px;">Фото загружено</span>`;
        };
        reader.readAsDataURL(file);
    }
});

function openGenerator(type) {
    currentGenType = type;
    switchTab('generator');
    
    // Очистка формы
    document.getElementById('file-input').value = '';
    uploadedBase64 = null;
    document.getElementById('result-image').style.display = 'none';
    document.getElementById('file-label').classList.remove('active');
    document.getElementById('file-label').innerHTML = `
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
        <span style="margin-top:8px;">Загрузить исходник</span>`;
    document.getElementById('gen-prompt').value = '';

    const titleMap = { 'info': 'Инфографика', 'photo': 'Нейрофотосессия', 'logo': 'Логотип' };
    document.getElementById('gen-title').innerText = titleMap[type];
    document.getElementById('photo-upload-section').style.display = (type === 'logo') ? 'none' : 'block';
}

async function startGeneration() {
    let prompt = document.getElementById('gen-prompt').value;
    if (currentGenType !== 'logo' && !uploadedBase64) return tg.showAlert("Загрузите фото!");
    if (!prompt) return tg.showAlert("Опишите задачу!");

    tg.HapticFeedback.impactOccurred('heavy');
    document.getElementById('btn-gen').style.display = 'none';
    document.getElementById('loading-box').style.display = 'block';
    document.getElementById('result-image').style.display = 'none';

    let res = await apiRequest('/api/generate', { type: currentGenType, prompt: prompt, image: uploadedBase64 });
    
    document.getElementById('btn-gen').style.display = 'block';
    document.getElementById('loading-box').style.display = 'none';

    if (res.success) {
        tg.HapticFeedback.notificationOccurred('success');
        document.getElementById('result-image').src = "data:image/jpeg;base64," + res.image;
        document.getElementById('result-image').style.display = 'block';
    } else {
        tg.HapticFeedback.notificationOccurred('error');
        if (res.need_sub) tg.showAlert("Пополните баланс или оформите подписку!");
        else tg.showAlert("Ошибка: " + res.error);
    }
}

async function submitTopup(method) {
    let amount = document.getElementById('topup-amount').value;
    if (!amount || amount < 10) return tg.showAlert("Минимум 10 ₽");
    tg.HapticFeedback.impactOccurred('medium');
    
    if (method === 'crypto') {
        let res = await apiRequest('/api/topup_crypto', { amount: amount });
        if (res.success) tg.openLink(res.url);
        else tg.showAlert("Ошибка создания счета");
    } else {
        await apiRequest('/api/topup_fiat', { amount: amount });
        tg.showAlert("Реквизиты отправлены вам в чат бота! Закройте окно.");
        tg.close();
    }
}

async function submitPromo() {
    let code = document.getElementById('promo-code').value;
    if (!code) return;
    tg.HapticFeedback.impactOccurred('medium');
    let res = await apiRequest('/api/promo', { code: code });
    if (res.success) {
        tg.showAlert("Баланс пополнен на " + res.reward + " ₽");
        switchTab('profile');
    } else {
        tg.showAlert(res.error);
    }
}
