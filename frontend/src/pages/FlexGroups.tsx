import { useEffect, useState } from "react";
import { getFlexGroups } from "../api/flex";

interface FlexGroupRaw {
    name: string;
    staff_name: string;
    day_of_week?: string;
    student_id?: string;
    student_name?: string;
    period?: string | number;
}

interface FlexGroupStudent {
    id: string;
    name: string;
}

interface FlexGroupCard {
    id: string;
    name: string;
    staff_name: string;
    period?: string | number;
    days: string[];
    students: FlexGroupStudent[];
}

export default function FlexGroups() {
    const [groups, setGroups] = useState<FlexGroupCard[]>([]);
    const [selectedGroup, setSelectedGroup] = useState<FlexGroupCard | null>(null);
    const [search, setSearch] = useState("");
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchFlexGroups = async () => {
            try {
                setLoading(true);
                const flexGroups: FlexGroupRaw[] = await getFlexGroups();

                const groupedMap = flexGroups.reduce<Record<string, FlexGroupCard>>((acc, g) => {
                    const key = `${g.name}-${g.staff_name}`;

                    if (!acc[key]) {
                        acc[key] = {
                            id: key,
                            name: g.name,
                            staff_name: g.staff_name,
                            period: g.period,
                            students: [],
                            days: []
                        };
                    }

                    if (g.day_of_week && !acc[key].days.includes(g.day_of_week)) {
                        acc[key].days.push(g.day_of_week);
                    }

                    if (g.student_id && !acc[key].students.some(s => s.id === g.student_id)) {
                        acc[key].students.push({ id: g.student_id, name: g.student_name ?? "" });
                    }

                    return acc;
                }, {});

                setGroups(Object.values(groupedMap));
                setError(null);
            } catch (err) {
                console.error("Failed to fetch flex groups:", err);
                setError("Couldn't load flex groups. Try refreshing.");
            } finally {
                setLoading(false);
            }
        };
        fetchFlexGroups();
    }, []);

    // Close modal on Escape
    useEffect(() => {
        if (!selectedGroup) return;
        const onKeyDown = (e: KeyboardEvent) => {
            if (e.key === "Escape") setSelectedGroup(null);
        };
        window.addEventListener("keydown", onKeyDown);
        return () => window.removeEventListener("keydown", onKeyDown);
    }, [selectedGroup]);

    const q = search.toLowerCase();
    const filteredGroups = groups
        .map(group => ({
            group,
            matchingStudents: q
                ? group.students.filter(s => s.name?.toLowerCase().includes(q))
                : []
        }))
        .filter(({ group, matchingStudents }) => {
            if (!q) return true;
            const teacherMatch = group.staff_name?.toLowerCase().includes(q);
            return teacherMatch || matchingStudents.length > 0;
        });

    return (
        <div>
            <h1>Flex Groups</h1>

            <input
                type="text"
                placeholder="Search by student or teacher..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                style={{
                    width: "100%",
                    padding: "10px 14px",
                    marginBottom: "24px",
                    borderRadius: "10px",
                    border: "1.5px solid var(--border)",
                    fontSize: "15px",
                    fontFamily: "var(--font-body)",
                    boxSizing: "border-box",
                }}
            />

            {loading && <p style={{ color: "var(--text)" }}>Loading flex groups…</p>}
            {error && <p style={{ color: "var(--red-500)" }}>{error}</p>}

            {!loading && !error && (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "20px" }}>
                    {filteredGroups.map(({ group, matchingStudents }) => (
                        <div
                            key={group.id}
                            role="button"
                            tabIndex={0}
                            onClick={() => setSelectedGroup(group)}
                            onKeyDown={(e) => {
                                if (e.key === "Enter" || e.key === " ") setSelectedGroup(group);
                            }}
                            style={{
                                border: "1px solid var(--border)",
                                borderRadius: "14px",
                                padding: "20px",
                                cursor: "pointer",
                                background: "white",
                                boxShadow: "0 2px 10px rgba(20, 50, 35, 0.06)",
                            }}
                        >
                            <h3 style={{ color: "var(--text-h)" }}>{group.name}</h3>
                            <p style={{ color: "var(--text)" }}>Teacher: {group.staff_name}</p>
                            <p style={{ color: "var(--text)" }}>{group.days.join(", ")} - Period {group.period}</p>
                            {search && matchingStudents.length > 0 && (
                                <p style={{ fontSize: "12px", color: "var(--text)" }}>
                                    Matching students: {matchingStudents.map(s => s.name).join(", ")}
                                </p>
                            )}
                        </div>
                    ))}
                </div>
            )}

            {selectedGroup && (
                <div
                    onClick={() => setSelectedGroup(null)}
                    style={{
                        position: "fixed",
                        inset: 0,
                        background: "rgba(15, 30, 22, 0.5)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        zIndex: 1000,
                    }}
                >
                    <div
                        onClick={(e) => e.stopPropagation()}
                        style={{
                            width: "40%",
                            maxWidth: "500px",
                            background: "white",
                            borderRadius: "16px",
                            padding: "25px",
                            boxShadow: "0 20px 50px rgba(15, 30, 22, 0.25)",
                            color: "var(--text-h)",
                        }}
                    >
                        <h2>{selectedGroup.name}</h2>
                        <h3 style={{ color: "var(--text-h)" }}>Teacher</h3>
                        <p style={{ color: "var(--text)" }}>{selectedGroup.staff_name}</p>
                        <h3 style={{ color: "var(--text-h)" }}>Students</h3>
                        <ul style={{ color: "var(--text)" }}>
                            {selectedGroup.students?.map((student) => (
                                <li key={student.id}>{student.name}</li>
                            ))}
                        </ul>
                        <button
                            onClick={() => setSelectedGroup(null)}
                            style={{
                                background: "var(--gradient-primary)",
                                color: "white",
                                border: "none",
                                borderRadius: "10px",
                                padding: "9px 18px",
                                fontFamily: "var(--font-body)",
                                fontWeight: 600,
                                cursor: "pointer",
                            }}
                        >
                            Close
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}