// app/static/js/calendar_userinfo.js

console.log("👤 calendar_userinfo.js loaded");

const userInfoBtn = document.getElementById("userInfoBtn");
const userInfoModal = document.getElementById("userInfoModal");

if (userInfoBtn && userInfoModal) {

    userInfoBtn.addEventListener("click", async () => {
        try {
            const res = await axios.get("/user_info");

            if (res.data.status === "success") {
                document.getElementById("userJoinDate").textContent =
                    "입사일: " + res.data.join_date;

                document.getElementById("userRemainVacation").textContent =
                    "남은 연차: " + res.data.remaining_days + "일";

                userInfoModal.classList.remove("hidden");
            }

        } catch (err) {
            console.error(err);
        }
    });

    document.getElementById("closeUserModal")?.addEventListener("click", () => {
        userInfoModal.classList.add("hidden");
    });
}
