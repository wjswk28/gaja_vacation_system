// app/static/js/calendar_modals.js

console.log("🟦 calendar_modals.js loaded");

// ------------- 모달 요소 ----------------
const adminModal = document.getElementById("adminModal");
const eventDetailModal = document.getElementById("eventDetailModal");
const flexModal = document.getElementById("flexModal");
const altLeaveModal = document.getElementById("altLeaveModal");


// ----------------- 공통 ------------------
function openModal(modal) {
    modal?.classList.remove("hidden");
    document.body.classList.add("overflow-hidden");
}
function closeModal(modal) {
    modal?.classList.add("hidden");
    document.body.classList.remove("overflow-hidden");
}


// ----------------- 관리 모달 ----------------
function openAdminModal() {
    openModal(adminModal);
}

document.getElementById("closeAdminModal")?.addEventListener("click", () => {
    closeModal(adminModal);
});


// ----------------- 상세 모달 --------------
window.openEventDetailModal = function (eventObj) {
    const modal = document.getElementById("eventDetailModal");
    if (!modal) return;

    modal.querySelector("#detailType").textContent = eventObj.extendedProps.type;
    modal.querySelector("#detailName").textContent = eventObj.extendedProps.name;
    modal.querySelector("#detailDate").textContent = eventObj.startStr;

    openModal(modal);
};

document.getElementById("closeEventDetail")?.addEventListener("click", () => {
    closeModal(eventDetailModal);
});


// ----------------- 근무자 버튼 선택 ----------------
window.selectedWorkers = [];

window.resetModalSelections = function () {
    selectedWorkers = [];
    document.querySelectorAll(".worker-btn").forEach(btn => {
        btn.classList.remove("ring-2", "ring-sky-400", "bg-sky-500", "text-white");
        btn.classList.add("bg-blue-100", "text-blue-700");
    });
};

document.querySelectorAll(".worker-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        const name = btn.dataset.name;

        if (!name) return;

        if (selectedWorkers.includes(name)) {
            selectedWorkers = selectedWorkers.filter(n => n !== name);
            btn.classList.remove("ring-2", "ring-sky-400", "bg-sky-500", "text-white");
            btn.classList.add("bg-blue-100", "text-blue-700");
        } else {
            selectedWorkers.push(name);
            btn.classList.add("ring-2", "ring-sky-400", "bg-sky-500", "text-white");
            btn.classList.remove("bg-blue-100", "text-blue-700");
        }
    });
});
