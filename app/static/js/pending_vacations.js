// =====================================================
// pending_vacations.html 전용 JS
// (승인 / 거절 기능)
// =====================================================

document.addEventListener("DOMContentLoaded", () => {
    lucide.createIcons();

    // ---------------------------------------------
    // 🟢 승인 버튼
    // ---------------------------------------------
    document.querySelectorAll(".approve-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
            const id = btn.dataset.id;

            try {
                const res = await axios.post(`/vacations/approve/${id}`);
                if (res.data.status === "success") {
                    const row = document.getElementById(`vac-row-${id}`);
                    if (row) row.remove();
                } else {
                    alert(res.data.message || "승인 처리 실패");
                }
            } catch (err) {
                alert("서버 오류가 발생했습니다.");
            }
        });
    });

    // ---------------------------------------------
    // 🔴 거절 버튼
    // ---------------------------------------------
    document.querySelectorAll(".reject-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
            const id = btn.dataset.id;

            try {
                const res = await axios.post(`/vacations/reject/${id}`);
                if (res.data.status === "success") {
                    const row = document.getElementById(`vac-row-${id}`);
                    if (row) row.remove();
                } else {
                    alert(res.data.message || "거절 처리 실패");
                }
            } catch (err) {
                alert("서버 오류가 발생했습니다.");
            }
        });
    });
});
