// app/static/js/calendar_actions.js

console.log("🔥 calendar_actions.js loaded");

document.getElementById("saveAdminEvent")?.addEventListener("click", async () => {

    const vacTypeEl = document.querySelector("input[name='vacType']:checked");
    if (!vacTypeEl) return alert("휴가 유형을 선택하세요.");

    const vacType = vacTypeEl.value;

    try {
        const res = await axios.post("/add_event", {
            start: window.selectedDate,
            end: window.selectedDate,
            type: vacType,
            worker_names: selectedWorkers,
        });

        if (res.data.status === "success") {
            closeModal(document.getElementById("adminModal"));
            window.calendar.refetchEvents();
        } else {
            alert(res.data.message);
        }

    } catch (err) {
        console.error(err);
        alert("서버 오류가 발생했습니다.");
    }
});
