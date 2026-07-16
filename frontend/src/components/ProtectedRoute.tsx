import {Navigate} from "react-router-dom";
import { useAuth } from "../context/authContext";

type Props = {
    children: React.ReactNode;
    roles?: (
        "admin" | "principal" | "teacher" | "aide"
    )[];
};

export default function ProtectedRoute({
    children,
    roles
}: Props) {
    const {
        user
    } = useAuth();
    
    if (!user) {
        return (
            <Navigate
                to="/login" replace
            />
        );
    }

    if (
        roles &&
        !roles.includes(user.role)
    ) {
        return (
            <Navigate
                to="/"
            />
        );
    }
    return children;
}