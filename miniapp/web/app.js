// ==========================================
// BALE EXCHANGE MINI APP
// مدیریت سفارش‌های ممبر
// ==========================================


// ==========================================
// تنظیمات
// ==========================================

// چون API و مینی‌اپ روی یک سرور هستند،
// از آدرس نسبی استفاده می‌کنیم.
const API_BASE_URL = "";

const REFRESH_INTERVAL = 5000;


// ==========================================
// عناصر صفحه
// ==========================================

const elements = {

    ordersContainer:
        document.getElementById("ordersContainer"),

    orderCount:
        document.getElementById("orderCount"),

    userBalance:
        document.getElementById("userBalance"),

    refreshButton:
        document.getElementById("refreshButton"),

    rewardToast:
        document.getElementById("rewardToast"),

    toastMessage:
        document.getElementById("toastMessage")

};


// ==========================================
// وضعیت برنامه
// ==========================================

const state = {

    orders: [],

    loading: false,

    claimingOrder: null,

    lastToastTime: 0

};


// ==========================================
// محیط بله
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

        throw new Error(
            "اطلاعات ورود مینی اپ دریافت نشد."
        );

    }

    const response = await fetch(
        API_BASE_URL + endpoint,
        {

            ...options,

            headers: {

                "Content-Type": "application/json",

                "X-Bale-Init-Data": initData,

                ...(options.headers || {})

            }

        }
    );

    let result;

    try {

        result = await response.json();

    } catch (error) {

        throw new Error(
            "پاسخ سرور قابل خواندن نیست."
        );

    }

    if (!response.ok || result.ok === false) {

        throw new Error(
            result.error || "ارتباط با سرور ناموفق بود."
        );

    }

    return result;

}


// ==========================================
// جلوگیری از تزریق HTML
// ==========================================

function escapeHtml(value) {

    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");

}


// ==========================================
// نمایش عدد فارسی
// ==========================================

function formatNumber(value) {

    return Number(value || 0).toLocaleString("fa-IR");

}


// ==========================================
// نمایش اعلان
// ==========================================

function showToast(message) {

    if (!elements.rewardToast) {
        return;
    }

    elements.toastMessage.textContent = message;

    elements.rewardToast.classList.remove("show");

    // اجرای دوباره انیمیشن
    void elements.rewardToast.offsetWidth;

    elements.rewardToast.classList.add("show");

    clearTimeout(showToast.timeout);

    showToast.timeout = setTimeout(() => {

        elements.rewardToast.classList.remove("show");

    }, 3500);

}


// ==========================================
// نمایش خطا
// ==========================================

function showError(message) {

    if (baleApp && typeof baleApp.showAlert === "function") {

        baleApp.showAlert(message);

        return;

    }

    showToast(message);

}


// ==========================================
// دریافت پروفایل کاربر
// ==========================================

async function loadProfile() {

    try {

        const result = await apiRequest(
            "/api/user/profile"
        );

        const coins = result.user?.coins ?? 0;

        if (elements.userBalance) {

            elements.userBalance.textContent =
                formatNumber(coins);

        }

    } catch (error) {

        console.error(
            "Profile error:",
            error
        );

    }

}


// ==========================================
// ساخت هشدار سفارش تضمینی
// ==========================================

function createGuaranteeWarning(order) {

    if (order.type !== "guaranteed") {
        return "";
    }

    const hours = formatNumber(
        order.guarantee_hours
    );

    const penalty = formatNumber(
        order.leave_penalty
    );

    return `

        <section class="guarantee-warning">

            <div class="warning-heading">

                <span class="warning-icon">⚠</span>

                <strong>
                    هشدار سفارش تضمینی
                </strong>

            </div>

            <p>
                در این سفارش باید حداقل
                <strong>${hours} ساعت</strong>
                عضو کانال بمانی.

                خروج زودتر از پایان این مدت،
                باعث کسر
                <strong>${penalty} سکه</strong>
                از موجودی تو می‌شود.
            </p>

        </section>

    `;

}


// ==========================================
// ساخت کارت سفارش
// ==========================================

function createOrderCard(order) {

    const id = Number(order.id);

    const isGuaranteed =
        order.type === "guaranteed";

    const typeLabel = isGuaranteed
        ? "تضمینی"
        : "معمولی";

    const reward = formatNumber(
        order.reward
    );

    const price = formatNumber(
        order.price_per_member
    );

    const totalCost = formatNumber(
        order.total_cost
    );

    const target = Number(
        order.target_count || 0
    );

    const joined = Number(
        order.joined_count || 0
    );

    const progress = target > 0
        ? Math.min(100, (joined / target) * 100)
        : 0;

    const title = escapeHtml(
        order.channel_title || "کانال"
    );

    const username = escapeHtml(
        order.channel_public_username ||
        order.channel_username ||
        ""
    );

    const avatar = order.avatar_url
        ? `
            <img
                src="${escapeHtml(order.avatar_url)}"
                alt="${title}"
                class="order-avatar-image"
                loading="lazy"
            >
        `
        : `
            <span class="avatar-fallback">
                ${escapeHtml(
                    (order.channel_title || "؟").trim().charAt(0)
                )}
            </span>
        `;

    const avatarUrl = escapeHtml(
        order.channel_url || "#"
    );

    const warning = createGuaranteeWarning(order);

    const rewardLabel = (
        isGuaranteed &&
        order.first_reward_available
    )
        ? "پاداش اولین عضویت"
        : "پاداش عضویت";

    return `

        <article
            class="channel-card order-card"
            data-order-id="${id}"
            data-order-type="${order.type}"
        >

            <!-- تصویر کانال -->

            <div class="channel-avatar-wrapper">

                <div class="channel-avatar">

                    ${avatar}

                </div>

                <span class="verified-icon">
                    ✓
                </span>

            </div>


            <!-- مشخصات کانال -->

            <div class="channel-details">

                <h1>
                    ${title}
                </h1>

                <span>
                    @${username.replace(/^@/, "")}
                </span>

            </div>


            <p class="channel-description">

                برای دریافت پاداش، در کانال عضو شو
                و سپس عضویتت را بررسی کن.

            </p>


            <!-- خلاصه سفارش -->

            <div class="order-summary">

                <div class="summary-item reward-summary">

                    <span class="summary-icon">
                        🪙
                    </span>

                    <div>

                        <strong>
                            ${reward} سکه
                        </strong>

                        <small>
                            ${rewardLabel}
                        </small>

                    </div>

                </div>


                <div class="summary-divider"></div>


                <div class="summary-item type-summary">

                    <span class="summary-icon">
                        ${isGuaranteed ? "🛡️" : "👥"}
                    </span>

                    <div>

                        <strong>
                            ${typeLabel}
                        </strong>

                        <small>
                            نوع سفارش
                        </small>

                    </div>

                </div>

            </div>


            <!-- جزئیات -->

            <section class="order-details">

                <div class="section-heading">

                    <h2>
                        جزئیات سفارش
                    </h2>

                    <span class="info-icon">
                        ⓘ
                    </span>

                </div>


                <div class="order-progress-box">

                    <div class="progress-header">

                        <span>
                            تعداد اعضای جذب‌شده
                        </span>

                        <strong>
                            ${formatNumber(joined)}
                            /
                            ${formatNumber(target)}
                        </strong>

                    </div>


                    <div class="progress-track">

                        <div
                            class="progress-fill"
                            style="width: ${progress}%"
                        ></div>

                    </div>


                    <div class="live-status">

                        <span class="live-dot"></span>

                        <span>
                            آمار زنده سفارش
                        </span>

                    </div>

                </div>


                <div class="order-info-row">

                    <span>
                        💰 قیمت هر ممبر
                    </span>

                    <strong>
                        ${price} سکه
                    </strong>

                </div>


                <div class="order-info-row">

                    <span>
                        🧾 هزینه کل سفارش
                    </span>

                    <strong>
                        ${totalCost} سکه
                    </strong>

                </div>


                ${
                    isGuaranteed
                    ? `
                        <div class="order-info-row">

                            <span>
                                📉 ممبر ازدست‌رفته
                            </span>

                            <strong class="lost-count">
                                ${formatNumber(order.lost_count)}
                            </strong>

                        </div>
                    `
                    : ""
                }

            </section>


            ${warning}


            <!-- دکمه‌ها -->

            <section class="order-actions">

                <button
                    class="join-button"
                    data-action="join"
                    data-url="${avatarUrl}"
                    type="button"
                >

                    <span>
                        عضویت در کانال
                    </span>

                    <span class="telegram-icon">
                        ➤
                    </span>

                </button>


                <button
                    class="check-button"
                    data-action="claim"
                    data-id="${id}"
                    data-type="${order.type}"
                    type="button"
                >

                    بررسی عضویت و دریافت پاداش

                </button>

            </section>

        </article>

    `;

}


// ==========================================
// نمایش سفارش‌ها
// ==========================================

function renderOrders(orders) {

    if (!elements.ordersContainer) {
        return;
    }

    if (!Array.isArray(orders) || orders.length === 0) {

        elements.ordersContainer.innerHTML = `

            <div class="empty-orders">

                <div class="empty-icon">
                    📭
                </div>

                <h2>
                    فعلاً سفارشی وجود ندارد
                </h2>

                <p>
                    به‌محض ثبت سفارش جدید،
                    اینجا نمایش داده می‌شود.
                </p>

            </div>

        `;

        return;

    }

    elements.ordersContainer.innerHTML =
        orders.map(createOrderCard).join("");


    // در صورت خراب بودن عکس، حرف اول نام کانال نمایش داده شود
    elements.ordersContainer
        .querySelectorAll(".order-avatar-image")
        .forEach(image => {

            image.addEventListener(
                "error",
                () => {

                    const fallback = document.createElement("span");

                    fallback.className = "avatar-fallback";

                    fallback.textContent =
                        image.alt.trim().charAt(0) || "؟";

                    image.replaceWith(fallback);

                },
                { once: true }
            );

        });

}


// ==========================================
// دریافت سفارش‌ها
// ==========================================

async function loadOrders() {

    if (state.loading) {
        return;
    }

    state.loading = true;

    try {

        const result = await apiRequest(
            "/api/orders?type=all&limit=50"
        );

        state.orders = result.orders || [];

        renderOrders(state.orders);

        if (elements.orderCount) {

            elements.orderCount.textContent =
                `${formatNumber(state.orders.length)} سفارش فعال`;

        }

    } catch (error) {

        console.error(
            "Orders error:",
            error
        );

        if (elements.orderCount) {
            elements.orderCount.textContent = error.message;
        }

        if (!state.orders.length) {

            elements.ordersContainer.innerHTML = `

                <div class="empty-orders error-box">

                    <div class="empty-icon">
                        ⚠️
                    </div>

                    <h2>
                        دریافت سفارش‌ها ناموفق بود
                    </h2>

                    <p>
                        اتصال اینترنت یا سرور را بررسی کن.
                    </p>

                    <button
                        class="check-button"
                        data-action="refresh"
                        type="button"
                    >
                        تلاش دوباره
                    </button>

                </div>

            `;

        }

    } finally {

        state.loading = false;

    }

}


// ==========================================
// رفتن به کانال
// ==========================================

function openChannel(url) {

    if (!url || url === "#") {

        showError(
            "لینک کانال در دسترس نیست."
        );

        return;

    }

    try {

        if (
            baleApp &&
            typeof baleApp.openLink === "function"
        ) {

            baleApp.openLink(url);

        } else {

            window.open(
                url,
                "_blank",
                "noopener,noreferrer"
            );

        }

    } catch (error) {

        console.error(
            "Open channel error:",
            error
        );

        showError(
            "باز کردن کانال ناموفق بود."
        );

    }

}


// ==========================================
// بررسی عضویت و دریافت پاداش
// ==========================================

async function claimOrder(button) {

    const orderId = Number(
        button.dataset.id
    );

    const orderType = button.dataset.type;

    if (
        !Number.isInteger(orderId) ||
        orderId <= 0
    ) {
        showError("شماره سفارش نامعتبر است.");
        return;
    }

    if (
        state.claimingOrder === orderId
    ) {
        return;
    }

    state.claimingOrder = orderId;

    const originalText = button.textContent;

    button.disabled = true;

    button.textContent = "در حال بررسی عضویت...";

    try {

        const result = await apiRequest(
            `/api/orders/${orderType}/${orderId}/claim`,
            {
                method: "POST",
                body: JSON.stringify({})
            }
        );

        showToast(
            `${formatNumber(result.reward)} سکه به موجودی تو اضافه شد.`
        );

        await loadProfile();

        await loadOrders();

    } catch (error) {

        showError(error.message);

        button.disabled = false;

        button.textContent = originalText;

    } finally {

        state.claimingOrder = null;

    }

}


// ==========================================
// رویدادهای سفارش‌ها
// ==========================================

elements.ordersContainer?.addEventListener(
    "click",
    async event => {

        const button = event.target.closest(
            "button[data-action]"
        );

        if (!button) {
            return;
        }

        const action = button.dataset.action;

        if (action === "join") {

            openChannel(
                button.dataset.url
            );

            return;

        }

        if (action === "claim") {

            await claimOrder(button);

            return;

        }

        if (action === "refresh") {

            await loadOrders();

        }

    }
);


// ==========================================
// تازه‌سازی دستی
// ==========================================

elements.refreshButton?.addEventListener(
    "click",
    async () => {

        await loadOrders();

        await loadProfile();

    }
);


// ==========================================
// شروع برنامه
// ==========================================

async function initializeApp() {

    if (baleApp) {

        try {

            baleApp.ready();
            baleApp.expand();

        } catch (error) {

            console.warn(
                "Bale WebApp initialization:",
                error
            );

        }

    }

    try {

        await apiRequest(
            "/api/auth/check"
        );

        await Promise.all([
            loadProfile(),
            loadOrders()
        ]);

        console.log(
            "Bale Exchange Mini App initialized."
        );

    } catch (error) {

        console.error(
            "Authentication error:",
            error
        );

        if (elements.orderCount) {
            elements.orderCount.textContent = error.message;
        }

    }

}


// ==========================================
// به‌روزرسانی زنده
// ==========================================

initializeApp();

setInterval(() => {

    if (
        document.visibilityState === "visible"
    ) {

        loadOrders();

    }

}, REFRESH_INTERVAL);