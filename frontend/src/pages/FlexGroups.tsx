import { useEffect, useState } from "react";
import { getFlexGroups } from "../api/flex";

export default function FlexGroups() {
    const [groups, setGroups] = useState<any[]>([]);
    const [selectedGroup, setSelectedGroup] = useState<any>(null);
    const [search, setSearch] = useState("");

    useEffect(() => {
        const fetchFlexGroups = async () => {
            const flexGroups = await getFlexGroups();
               const grouped = Object.values(
                flexGroups.reduce((acc: any, g: any) => {
                    // Group by name + teacher only — one card per group, not per day
                    const key = `${g.name}-${g.staff_name}`;
                    if (!acc[key]) {
                        acc[key] = {
                            ...g,
                            students: [],
                            days: []
                        };
                    }
                    // Collect each day this group meets
                    if (g.day_of_week && !acc[key].days.includes(g.day_of_week)) {
                        acc[key].days.push(g.day_of_week);
                    }
                    // Merge students, dedupe by id
                    g.student_id && !acc[key].students.find((s: any) => s.id === g.student_id) &&
                        acc[key].students.push({ id: g.student_id, name: g.student_name });
                    return acc;
                }, {})
            );
            setGroups(grouped);
        };
        fetchFlexGroups();
    }, []);

    const filteredGroups = groups.filter((group: any) => {
        const q = search.toLowerCase();
        if (!q) return true;
        const teacherMatch = group.staff_name?.toLowerCase().includes(q);
        const studentMatch = group.students?.some((s: any) =>
            s.name?.toLowerCase().includes(q)
        );
        return teacherMatch || studentMatch;
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

            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "20px" }}>
                {filteredGroups.map((group: any) => (
                    <div
                        key={group.id}
                        onClick={() => setSelectedGroup(group)}
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
                        {search && (
                            <p style={{ fontSize: "12px", color: "#888" }}>
                                {group.students?.filter((s: any) =>
                                    s.name?.toLowerCase().includes(search.toLowerCase())
                                ).length > 0 && (
                                    <>
                                        Matching students:{" "}
                                        {group.students
                                            .filter((s: any) =>
                                                s.name?.toLowerCase().includes(search.toLowerCase())
                                            )
                                            .map((s: any) => s.name)
                                            .join(", ")}
                                    </>
                                )}
                            </p>
                        )}
                    </div>
                ))}
            </div>

            {selectedGroup && (
                <div
                    style={{
                        position: "fixed",
                        top: "20%",
                        left: "30%",
                        width: "40%",
                        background: "white",
                        border: "1px solid black",
                        borderRadius: "12px",
                        padding: "25px",
                        boxShadow: "0 5px 20px #999",
                    }}
                >
                    <h2>{selectedGroup.name}</h2>
                    <h3>Teacher</h3>
                    <p>{selectedGroup.staff_name}</p>
                    <h3>Students</h3>
                    <ul>
                        {selectedGroup.students?.map((student: any) => (
                            <li key={student.id}>{student.name}</li>
                        ))}
                    </ul>
                    <button onClick={() => setSelectedGroup(null)}>Close</button>
                </div>
            )}
        </div>
    );
}