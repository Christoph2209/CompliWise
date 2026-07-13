import { Navigate } from "react-router-dom";
import { useAuth } from "../context/authContext";
import type { Role } from "../context/authTypes";


export default function RoleRoute({

    allowed,
    children

}:{
    allowed:Role[],
    children:React.ReactNode
}){


    const {user}=useAuth();



    if(!user){
        return (
            <Navigate
                to="/login"
            />
        );
    }



    if(!allowed.includes(user.role)){
        return (
            <Navigate
                to="/"
            />
        );
    }



    return children;
}