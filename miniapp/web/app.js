
// ==========================================
// BALE EXCHANGE MINI APP
// ارتباط فرانت‌اند با API
// ==========================================

const API_BASE_URL = "http://127.0.0.1:8080";

// ==========================================
// عناصر صفحه
// ==========================================

const elements = {
    userBalance: document.getElementById("userBalance"),
    orderCount: document.getElementById("orderCount"),
    channelName: document.getElementById("channelName"),
    channelUsername: document.getElementById("channelUsername"),
    channelAvatar: document.getElementById("channelAvatar"),
    orderType: document.getElementById("orderType"),
    orderReward: document.getElementById("orderReward"),
    guaranteeWarning: document.getElementById("guaranteeWarning"),
    guaranteeText: document.getElementById("guaranteeText"),
    joinButton: document.getElementById("joinButton"),
    checkButton: document.getElementById("checkButton"),
    profileButton: document.getElementById("profileButton")
};

// ==========================================
// اطلاعات محیط بله
// ==========================================

const baleApp = window.Bale?.WebApp;

// ==========================================
// دریافت اطلاعات ورود
// ==========================================

function getInitData() {
    if (!baleApp) {
        return "";
    }

    return baleApp.initData || "";
}

// ==========================================
// درخواست به API
// ==========================================

async function apiRequest(endpoint, options = {}) {
    const initData = getInitData();

    if (!initData) {
        throw new Error("اطلاعات ورود مینی اپ دریافت نشد.");
    }

    const response = await fetch(
        `${API_BASE_URL}${endpoint}`,
        {
            ...options,
            headers: {
                "Content-Type": "application/json",
                "X-Bale-Init-Data": initData,
                ...(options.headers || {})
            }
        }
    );

    const result = await response.json();

    if (!response.ok || result.ok === false) {
        throw new Error(
            result.error || "ارتباط با سرور ناموفق بود."
        );
    }

    return result;
}

// ==========================================
// نمایش خطا
// ==========================================

function showError(message) {
    if (elements.orderCount) {
        elements.orderCount.textContent = message;
    }
}

// ==========================================
// بررسی ورود کاربر
// ==========================================

async function checkAuthentication() {
    try {
        const result = await apiRequest("/api/auth/check");

        console.log("Authenticated user:", result.user);

        return result.user;

    } catch (error) {
        showError(error.message);
        return null;
    }
}

// ==========================================
// آماده‌سازی مینی اپ
// ==========================================

async function initializeApp() {
    if (baleApp) {
        baleApp.ready();
        baleApp.expand();
    }

    const user = await checkAuthentication();

    if (!user) {
        return;
    }

    console.log("Mini App initialized.");
}

// ==========================================
// دکمه عضویت
// ==========================================

elements.joinButton?.addEventListener("click", () => {
    showError("ابتدا باید سفارش‌های واقعی از API دریافت شوند.");
});

// ==========================================
// دکمه بررسی عضویت
// ==========================================

elements.checkButton?.addEventListener("click", () => {
    showError("بررسی عضویت پس از اتصال منطق سفارش فعال می‌شود.");
});

// ==========================================
// دکمه پروفایل
// ==========================================

elements.profileButton?.addEventListener("click", () => {
    if (baleApp) {
        baleApp.showAlert("بخش پروفایل در حال آماده‌سازی است.");
    }
});

// ==========================================
// شروع برنامه
// ==========================================

initializeApp();
