import {
  createContext,
  useContext,
  useState
} from "react";

import type { User } from "./authTypes";

type AuthContextType = {

  user: User | null;

  login: (
    email: string,
    password: string
  ) => Promise<void>;

  logout: () => void;

};



const AuthContext =
  createContext<AuthContextType | null>(null);



export function AuthProvider({
  children
}:{
  children: React.ReactNode;
}) {


  const [user,setUser] =
    useState<User | null>(() => {

      const saved =
        localStorage.getItem("user");

      return saved
        ? JSON.parse(saved)
        : null;

    });



  async function login(
    email:string,
    password:string
  ){


    const response =
      await fetch(
        "http://localhost:8000/login",
        {
          method:"POST",
          headers:{
            "Content-Type":"application/json"
          },
          body:JSON.stringify({
            email,
            password
          })
        }
      );


    if(!response.ok){
      throw new Error(
        "Login failed"
      );
    }


    const data =
      await response.json();


    setUser(data);


    localStorage.setItem(
      "user",
      JSON.stringify(data)
    );

  }



  function logout(){

    setUser(null);

    localStorage.removeItem(
      "user"
    );

  }



  return (

    <AuthContext.Provider
      value={{
        user,
        login,
        logout
      }}
    >

      {children}

    </AuthContext.Provider>

  );

}



export function useAuth(){

  const context =
    useContext(AuthContext);


  if(!context){

    throw new Error(
      "useAuth must be used inside AuthProvider"
    );

  }


  return context;

}