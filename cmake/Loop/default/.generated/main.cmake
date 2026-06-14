include("${CMAKE_CURRENT_LIST_DIR}/rule.cmake")
include("${CMAKE_CURRENT_LIST_DIR}/file.cmake")

set(Loop_default_library_list )

# Handle files with suffix (s|as|asm|AS|ASM|As|aS|Asm), for group default-XC8
if(Loop_default_default_XC8_FILE_TYPE_assemble)
add_library(Loop_default_default_XC8_assemble OBJECT ${Loop_default_default_XC8_FILE_TYPE_assemble})
    Loop_default_default_XC8_assemble_rule(Loop_default_default_XC8_assemble)
    list(APPEND Loop_default_library_list "$<TARGET_OBJECTS:Loop_default_default_XC8_assemble>")

endif()

# Handle files with suffix S, for group default-XC8
if(Loop_default_default_XC8_FILE_TYPE_assemblePreprocess)
add_library(Loop_default_default_XC8_assemblePreprocess OBJECT ${Loop_default_default_XC8_FILE_TYPE_assemblePreprocess})
    Loop_default_default_XC8_assemblePreprocess_rule(Loop_default_default_XC8_assemblePreprocess)
    list(APPEND Loop_default_library_list "$<TARGET_OBJECTS:Loop_default_default_XC8_assemblePreprocess>")

endif()

# Handle files with suffix [cC], for group default-XC8
if(Loop_default_default_XC8_FILE_TYPE_compile)
add_library(Loop_default_default_XC8_compile OBJECT ${Loop_default_default_XC8_FILE_TYPE_compile})
    Loop_default_default_XC8_compile_rule(Loop_default_default_XC8_compile)
    list(APPEND Loop_default_library_list "$<TARGET_OBJECTS:Loop_default_default_XC8_compile>")

endif()


# Main target for this project
add_executable(Loop_default_image_O_Ckr_jZ ${Loop_default_library_list})

set_target_properties(Loop_default_image_O_Ckr_jZ PROPERTIES
    OUTPUT_NAME "default"
    SUFFIX ".elf"
    ADDITIONAL_CLEAN_FILES "${output_extensions}"
    RUNTIME_OUTPUT_DIRECTORY "${Loop_default_output_dir}")
target_link_libraries(Loop_default_image_O_Ckr_jZ PRIVATE ${Loop_default_default_XC8_FILE_TYPE_link})

# Add the link options from the rule file.
Loop_default_link_rule( Loop_default_image_O_Ckr_jZ)


