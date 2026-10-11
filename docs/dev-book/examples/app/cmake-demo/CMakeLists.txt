cmake_minimum_required(VERSION 3.16)
project(cmake_demo C)

add_executable(cmake-demo main.c)
target_compile_options(cmake-demo PRIVATE -Wall -Wextra)
install(TARGETS cmake-demo DESTINATION bin)
