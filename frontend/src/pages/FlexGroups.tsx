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
                    borderRadius: "8px",
                    border: "1px solid #ccc",
                    fontSize: "15px",
                    boxSizing: "border-box",
                }}
            />

            {loading && <p>Loading flex groups…</p>}
            {error && <p style={{ color: "crimson" }}>{error}</p>}

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
                                border: "1px solid #ccc",
                                borderRadius: "12px",
                                padding: "20px",
                                cursor: "pointer",
                                background: "#f5f5f5",
                            }}
                        >
                            <h3>{group.name}</h3>
                            <p>Teacher: {group.staff_name}</p>
                            <p>{group.days.join(", ")} - Period {group.period}</p>
                            {search && matchingStudents.length > 0 && (
                                <p style={{ fontSize: "12px", color: "#888" }}>
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
                        background: "rgba(0,0,0,0.4)",
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
                            border: "1px solid black",
                            borderRadius: "12px",
                            padding: "25px",
                            boxShadow: "0 5px 20px #999",
                            color: "#000000",
                        }}
                    >
                        <h2 style={{ color: "black" }}>{selectedGroup.name}</h2>
                        <h3>Teacher</h3>
                        <p>{selectedGroup.staff_name}</p>
                        <h3>Students</h3>
                        <ul>
                            {selectedGroup.students?.map((student) => (
                                <li key={student.id}>{student.name}</li>
                            ))}
                        </ul>
                        <button onClick={() => setSelectedGroup(null)}>Close</button>
                    </div>
                </div>
            )}
        </div>
    );
}