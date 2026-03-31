import axios from "axios";

const client = axios.create({
  baseURL: "http://localhost:8000",
  timeout: 60000,
});

export default client;
