module bit_shift_low_pass_filter #(
    parameter IMAGE_DIM,
    parameter IMAGE_DIM_BS
)(
    input  wire         clk,
    input  wire [1:0]   kernel_size,
    input  wire         pixel_valid_in,
    input  wire         soc_in,
    input  wire         eoc_in,
    input  wire         solf_in,
    input  wire         eolf_in,
    input  wire [23:0]  pixel_in,
    output logic        pixel_valid_out,
    output logic        soc_out,
    output logic        eoc_out,
    output logic        solf_out,
    output logic        eolf_out,
    output logic [14:0] pixel_out_red,
    output logic [14:0] pixel_out_green,
    output logic [14:0] pixel_out_blue
);

    // ============================================================
    // Kernel definitions
    // ============================================================

    // kernel_size:
    // 00 -> 1x1 (no blur)
    // 01 -> 3x3
    // 10 -> 5x5
    // 11 -> 7x7

    // Each kernel value stores the bit-shift amount applied to the source pixel.
    // Example: shift amount 2 means multiply pixel by 2^2 = 4.
    localparam logic [1:0] kernel_3 [0:8] = '{
        0, 1, 0,
        1, 2, 1,
        0, 1, 0
    }; // >> 4, sum = 16

    localparam logic [1:0] kernel_5 [0:24] = '{
        0, 1, 1, 1, 0,
        1, 2, 2, 2, 1,
        1, 2, 2, 2, 1,
        1, 2, 2, 2, 1,
        0, 1, 1, 1, 0
    }; // >> 6, sum = 64

    localparam logic [1:0] kernel_7 [0:48] = '{
        0, 0, 1, 1, 1, 0, 0,
        0, 1, 2, 2, 2, 1, 0,
        1, 2, 2, 2, 2, 2, 1,
        1, 2, 2, 2, 2, 2, 1,
        1, 2, 2, 2, 2, 2, 1,
        0, 1, 2, 2, 2, 1, 0,
        0, 0, 1, 1, 1, 0, 0
    }; // >> 7, sum = 128

    // ============================================================
    // Parameters used by the original design
    // ============================================================

    // Full logical buffer size used by the original shift-register design:
    // 6 full rows + 6 extra columns = support for 7x7 window.
    localparam int unsigned BUFFER_LAST  = (6 << IMAGE_DIM_BS) + 6;
    localparam int unsigned BUFFER_SIZE  = BUFFER_LAST + 1;
    localparam int unsigned BUFFER_PTR_W = $clog2(BUFFER_SIZE);

    // Original insertion locations in the shift-register design.
    // These are the exact logical indices that the original code wrote to.
    localparam int unsigned INSERT_IDX_3 = (2 << IMAGE_DIM_BS) + 2;
    localparam int unsigned INSERT_IDX_5 = (4 << IMAGE_DIM_BS) + 4;
    localparam int unsigned INSERT_IDX_7 = (6 << IMAGE_DIM_BS) + 6;

    // Original raw fallback taps used when edge pixels are not convolved.
    localparam int unsigned RAW_TAP_3 = (1 << IMAGE_DIM_BS) + 1;
    localparam int unsigned RAW_TAP_5 = (2 << IMAGE_DIM_BS) + 2;
    localparam int unsigned RAW_TAP_7 = (3 << IMAGE_DIM_BS) + 3;

    // ============================================================
    // State / flags
    // ============================================================

    // Remember whether the next delayed SOC/EOC should also be SOLF/EOLF.
    logic next_soc_is_solf = 0;
    logic next_eoc_is_eolf = 0;

    // Input pixel position counters.
    logic [IMAGE_DIM_BS-1:0] row_in_count    = 0;
    logic [IMAGE_DIM_BS-1:0] column_in_count = 0;

    // Counters used to delay output validity at the start and end of a capture.
    localparam int unsigned LAG_BUFFER_MAX  = (6 << IMAGE_DIM_BS) + 6;
    localparam int unsigned LAG_BUFFER_SIZE = $clog2(LAG_BUFFER_MAX + 1);

    logic [LAG_BUFFER_SIZE-2:0] start_lag_buffer_count = 0;
    logic [LAG_BUFFER_SIZE-1:0] end_lag_buffer_count   = 0;

    // Flags indicating whether delayed output stream has started / is flushing.
    logic soc_lag_flag = 0;
    logic eoc_lag_flag = 0;

    // One-shot pulse helpers for delayed SOC/EOC.
    logic soc_out_pulse = 0;
    logic eoc_out_pulse = 0;

    // RGB input split from 24-bit input bus.
    logic [7:0] pixel_in_red;
    logic [7:0] pixel_in_green;
    logic [7:0] pixel_in_blue;

    assign pixel_in_red   = pixel_in[23:16];
    assign pixel_in_green = pixel_in[15:8];
    assign pixel_in_blue  = pixel_in[7:0];

    // Convolution accumulators.
    logic [14:0] convoluted_red   = 0;
    logic [14:0] convoluted_green = 0;
    logic [14:0] convoluted_blue  = 0;

    // This registered flag is intentionally kept because the original code
    // used it as a one-cycle-delayed "use convolved or raw" decision.
    logic next_is_convolved_flag = 0;

    // Output pixel position counters.
    logic [IMAGE_DIM_BS-1:0] row_out_count    = 0;
    logic [IMAGE_DIM_BS-1:0] column_out_count = 0;

    // ============================================================
    // Pointer-based buffer storage
    // ============================================================

    // Physical storage is still the full original 7x7-sized buffer.
    // The goal is to keep the original LOGICAL behaviour exactly the same,
    // but replace the physical full-buffer shift with pointer arithmetic.
    logic [7:0] pixel_buffer_red   [0:BUFFER_SIZE-1];
    logic [7:0] pixel_buffer_green [0:BUFFER_SIZE-1];
    logic [7:0] pixel_buffer_blue  [0:BUFFER_SIZE-1];

    // buffer_head points to the physical location corresponding to LOGICAL index 0.
    //
    // In pointer form:
    //   advance the head by 1
    //
    // Then the physical location that USED TO BE logical[0] becomes the place
    // where the new logical[BUFFER_LAST] value must be written.
    logic [BUFFER_PTR_W-1:0] buffer_head = 0;

    // Advance the logical buffer whenever the original design would have shifted.
    logic advance_buffer;

    assign advance_buffer = pixel_valid_in
                          || (eoc_lag_flag && ((row_in_count == 0) && (column_in_count == 0)));

    // ============================================================
    // Helper functions
    // ============================================================

    // Return the next head location for the full logical buffer.
    function automatic [BUFFER_PTR_W-1:0] inc_full_head(
        input logic [BUFFER_PTR_W-1:0] idx
    );
        begin
            if (idx == BUFFER_LAST) begin
                inc_full_head = '0;
            end
            else begin
                inc_full_head = idx + BUFFER_PTR_W'(1);
            end
        end
    endfunction

    // Convert a logical index into a physical array index using the FULL buffer.
    // This matches the original design, which always shifted the full buffer,
    // even for 3x3 and 5x5.
    function automatic [BUFFER_PTR_W-1:0] buf_phys_idx(
        input logic [BUFFER_PTR_W-1:0] head,
        input int unsigned logical_idx
    );
        int unsigned tmp;
        begin
            tmp = head + logical_idx;
            if (tmp >= BUFFER_SIZE) begin
                tmp = tmp - BUFFER_SIZE;
            end
            buf_phys_idx = BUFFER_PTR_W'(tmp);
        end
    endfunction

    // ============================================================
    // Image buffer management
    // ============================================================
    //
    // This block preserves the ORIGINAL LOGICAL behaviour exactly:
    //
    // 1) Whenever the original code would shift left, we instead increment
    //    buffer_head by 1.
    //
    // 2) The new logical last element is written into the OLD head location.
    //
    // 3) For kernel_size != 7x7, the original code forced logical[last] = 0.
    //
    // 4) For 7x7 during flush (no pixel_valid_in), the original code did NOT
    //    write zero to the last element. Because of the shift structure, that
    //    means old logical[last] is duplicated into new logical[last].
    //
    // 5) For pixel_valid_in, the original code additionally wrote the incoming
    //    pixel into logical insert_idx (258 / 516 / 774 depending on kernel).
    //
    // This implementation reproduces those exact rules using pointer-based
    // addressing instead of a full-array shift.
    // ============================================================
    always_ff @(posedge clk) begin : Image_Buffer
        logic [BUFFER_PTR_W-1:0] old_head;
        logic [BUFFER_PTR_W-1:0] new_head;
        logic [BUFFER_PTR_W-1:0] old_last_phys;
        logic [BUFFER_PTR_W-1:0] insert_phys;

        old_head      = buffer_head;
        new_head      = inc_full_head(buffer_head);
        old_last_phys = buf_phys_idx(buffer_head, BUFFER_LAST);
        insert_phys   = '0;

        // --------------------------------------------------------
        // Start of capture handling
        // --------------------------------------------------------
        if (soc_in) begin
            row_in_count           <= 0;
            column_in_count        <= 0;
            soc_lag_flag           <= 0;
            start_lag_buffer_count <= 1;
        end

        // --------------------------------------------------------
        // End of capture handling
        // --------------------------------------------------------
        if (eoc_in) begin
            eoc_lag_flag    <= 1;
            row_in_count    <= 0;
            column_in_count <= 0;
        end

        // Reset end flush counter once delayed SOC is emitted.
        if (soc_out) begin
            end_lag_buffer_count <= 0;
        end

        // Reset delayed-stream state once the full light field is output.
        if (eolf_out) begin
            row_in_count           <= 0;
            column_in_count        <= 0;
            start_lag_buffer_count <= 0;
            end_lag_buffer_count   <= 0;
            soc_lag_flag           <= 0;
            eoc_lag_flag           <= 0;
            soc_out_pulse          <= 0;
            eoc_out_pulse          <= 0;
        end

        // --------------------------------------------------------
        // End-lag flushing logic
        // --------------------------------------------------------
        if (eoc_lag_flag && (((row_in_count == 0) && (column_in_count == 0)) || pixel_valid_in)) begin
            end_lag_buffer_count <= end_lag_buffer_count + $bits(end_lag_buffer_count)'(1);

            case (kernel_size)
                2'b00 : begin
                    eoc_lag_flag  <= 0;
                    eoc_out_pulse <= 1;
                end

                2'b01 : begin
                    if (end_lag_buffer_count == (1 << IMAGE_DIM_BS)) begin
                        eoc_out_pulse <= 1;
                    end
                    if (end_lag_buffer_count == (1 << IMAGE_DIM_BS) + 1) begin
                        eoc_lag_flag <= 0;
                    end
                end

                2'b10 : begin
                    if (end_lag_buffer_count == (2 << IMAGE_DIM_BS) + 1) begin
                        eoc_out_pulse <= 1;
                    end
                    if (end_lag_buffer_count == (2 << IMAGE_DIM_BS) + 2) begin
                        eoc_lag_flag <= 0;
                    end
                end

                2'b11 : begin
                    if (end_lag_buffer_count == (3 << IMAGE_DIM_BS) + 2) begin
                        eoc_out_pulse <= 1;
                    end
                    if (end_lag_buffer_count == (3 << IMAGE_DIM_BS) + 3) begin
                        eoc_lag_flag <= 0;
                    end
                end
            endcase
        end

        // --------------------------------------------------------
        // Pointer-based replacement for the original shift loop
        // --------------------------------------------------------
        if (advance_buffer) begin
            // Move logical index 0 -> 1, 1 -> 2, etc. by advancing the head.
            buffer_head <= new_head;

            case (kernel_size)
                // ------------------------------------------------
                // 1x1 (buffer contents not used by output logic)
                // Original shift behaviour still forced logical[last] = 0.
                // ------------------------------------------------
                2'b00 : begin
                    pixel_buffer_red[old_head]   <= 8'd0;
                    pixel_buffer_green[old_head] <= 8'd0;
                    pixel_buffer_blue[old_head]  <= 8'd0;
                end

                // ------------------------------------------------
                // 3x3
                // Original behaviour:
                //   - shift full 775-deep buffer
                //   - force logical[last] = 0
                //   - if pixel_valid_in, write new pixel into logical[258]
                // ------------------------------------------------
                2'b01 : begin
                    // New logical[last] = 0
                    pixel_buffer_red[old_head]   <= 8'd0;
                    pixel_buffer_green[old_head] <= 8'd0;
                    pixel_buffer_blue[old_head]  <= 8'd0;

                    // New logical[258] = pixel_in when valid
                    if (pixel_valid_in) begin
                        insert_phys = buf_phys_idx(new_head, INSERT_IDX_3);

                        pixel_buffer_red[insert_phys]   <= pixel_in_red;
                        pixel_buffer_green[insert_phys] <= pixel_in_green;
                        pixel_buffer_blue[insert_phys]  <= pixel_in_blue;
                    end
                end

                // ------------------------------------------------
                // 5x5
                // Original behaviour:
                //   - shift full 775-deep buffer
                //   - force logical[last] = 0
                //   - if pixel_valid_in, write new pixel into logical[516]
                // ------------------------------------------------
                2'b10 : begin
                    // New logical[last] = 0
                    pixel_buffer_red[old_head]   <= 8'd0;
                    pixel_buffer_green[old_head] <= 8'd0;
                    pixel_buffer_blue[old_head]  <= 8'd0;

                    // New logical[516] = pixel_in when valid
                    if (pixel_valid_in) begin
                        insert_phys = buf_phys_idx(new_head, INSERT_IDX_5);

                        pixel_buffer_red[insert_phys]   <= pixel_in_red;
                        pixel_buffer_green[insert_phys] <= pixel_in_green;
                        pixel_buffer_blue[insert_phys]  <= pixel_in_blue;
                    end
                end

                // ------------------------------------------------
                // 7x7
                // Original behaviour:
                //   - shift full 775-deep buffer
                //   - if pixel_valid_in, write new pixel into logical[last]
                //   - else during flush, duplicate old logical[last] into new logical[last]
                // ------------------------------------------------
                2'b11 : begin
                    if (pixel_valid_in) begin
                        // For 7x7, insert location is logical[last], whose new
                        // physical location is old_head after the head advances.
                        pixel_buffer_red[old_head]   <= pixel_in_red;
                        pixel_buffer_green[old_head] <= pixel_in_green;
                        pixel_buffer_blue[old_head]  <= pixel_in_blue;
                    end
                    else begin
                        // During 7x7 flush with no input pixel, the original code
                        // left the last element unwritten. Because the rest of the
                        // buffer shifted, that effectively duplicated old logical[last]
                        // into new logical[last].
                        pixel_buffer_red[old_head]   <= pixel_buffer_red[old_last_phys];
                        pixel_buffer_green[old_head] <= pixel_buffer_green[old_last_phys];
                        pixel_buffer_blue[old_head]  <= pixel_buffer_blue[old_last_phys];
                    end
                end
            endcase
        end

        // --------------------------------------------------------
        // Startup lag bookkeeping
        // --------------------------------------------------------
        if (pixel_valid_in) begin
            case (kernel_size)
                2'b00 : begin
                    soc_lag_flag  <= 1;
                    soc_out_pulse <= 1;
                end

                2'b01 : begin
                    if (!soc_lag_flag) begin
                        start_lag_buffer_count <= start_lag_buffer_count + $bits(start_lag_buffer_count)'(1);
                        if (start_lag_buffer_count == (1 << IMAGE_DIM_BS) + 1) begin
                            soc_lag_flag  <= 1;
                            soc_out_pulse <= 1;
                        end
                    end
                end

                2'b10 : begin
                    if (!soc_lag_flag) begin
                        start_lag_buffer_count <= start_lag_buffer_count + $bits(start_lag_buffer_count)'(1);
                        if (start_lag_buffer_count == (2 << IMAGE_DIM_BS) + 2) begin
                            soc_lag_flag  <= 1;
                            soc_out_pulse <= 1;
                        end
                    end
                end

                2'b11 : begin
                    if (!soc_lag_flag) begin
                        start_lag_buffer_count <= start_lag_buffer_count + $bits(start_lag_buffer_count)'(1);
                        if (start_lag_buffer_count == (3 << IMAGE_DIM_BS) + 3) begin
                            soc_lag_flag  <= 1;
                            soc_out_pulse <= 1;
                        end
                    end
                end
            endcase

            // Track incoming pixel row / column position.
            if (column_in_count == IMAGE_DIM-1) begin
                column_in_count <= 0;
                row_in_count    <= row_in_count + $bits(row_in_count)'(1);
            end
            else begin
                column_in_count <= column_in_count + $bits(column_in_count)'(1);
            end
        end

        // --------------------------------------------------------
        // Clear one-shot pulse flags
        // --------------------------------------------------------
        if (soc_out_pulse && pixel_valid_in) begin
            soc_out_pulse <= 0;
        end

        if (eoc_out_pulse && (((column_in_count != 0) && pixel_valid_in) || (column_in_count == 0))) begin
            eoc_out_pulse <= 0;
        end
    end

    // ============================================================
    // Convolution + output logic
    // ============================================================
    //
    // This block is kept logically the same as the original working version.
    // The only difference is that buffer reads now go through buf_phys_idx()
    // so they access the pointer-based representation of the same logical data.
    //
    // IMPORTANT:
    // next_is_convolved_flag is intentionally preserved as a REGISTERED flag,
    // because the original code used the previous-cycle decision.
    // ============================================================
    always_ff @(posedge clk) begin : Convolution
        // Reset accumulators each cycle.
        convoluted_red   = 0;
        convoluted_green = 0;
        convoluted_blue  = 0;

        // Remember whether next delayed SOC/EOC is also SOLF/EOLF.
        if (solf_in) begin
            next_soc_is_solf <= 1;
        end

        if (eolf_in) begin
            next_eoc_is_eolf <= 1;
        end

        if (solf_out) begin
            next_soc_is_solf <= 0;
        end

        // Reset output-side state after a full delayed light field completes.
        if (eolf_out) begin
            pixel_valid_out        <= 0;
            soc_out                <= 0;
            eoc_out                <= 0;
            eolf_out               <= 0;
            solf_out               <= 0;
            next_soc_is_solf       <= 0;
            next_eoc_is_eolf       <= 0;
            next_is_convolved_flag <= 0;
            row_out_count          <= 0;
            column_out_count       <= 0;
        end

        case (kernel_size)
            // ----------------------------------------------------
            // No blur
            // ----------------------------------------------------
            2'b00 : begin
                soc_out  <= soc_in;
                eoc_out  <= eoc_in;
                solf_out <= solf_in;
                eolf_out <= eolf_in;

                // Convert integer 8-bit RGB into Q8.7.
                pixel_out_red   <= (pixel_in_red   << 7);
                pixel_out_green <= (pixel_in_green << 7);
                pixel_out_blue  <= (pixel_in_blue  << 7);

                pixel_valid_out <= pixel_valid_in;

                if (eoc_in) begin
                    row_out_count    <= 0;
                    column_out_count <= 0;
                end
                else if (pixel_valid_in) begin
                    if (column_out_count == IMAGE_DIM-1) begin
                        column_out_count <= 0;
                        row_out_count    <= row_out_count + $bits(row_out_count)'(1);
                    end
                    else begin
                        column_out_count <= column_out_count + $bits(column_out_count)'(1);
                    end
                end
            end

            // ----------------------------------------------------
            // 3x3 blur
            // ----------------------------------------------------
            2'b01 : begin
                // Decide whether NEXT output should be convolved.
                if ((row_out_count == 0)
                    || (row_out_count == IMAGE_DIM-1)
                    || ((row_out_count == IMAGE_DIM-2) && (column_out_count == IMAGE_DIM-1))
                    || (column_out_count == IMAGE_DIM-2)
                    || (column_out_count == IMAGE_DIM-3)) begin
                    next_is_convolved_flag <= 0;
                end
                else begin
                    next_is_convolved_flag <= 1;
                end

                // Convolve from logical 3x3 window taps.
                for (int kernel_row = 0; kernel_row < 3; kernel_row++) begin
                    for (int kernel_column = 0; kernel_column < 3; kernel_column++) begin
                        convoluted_red =
                            convoluted_red
                            + (
                                pixel_buffer_red[
                                    buf_phys_idx(
                                        buffer_head,
                                        (kernel_row << IMAGE_DIM_BS) + kernel_column
                                    )
                                ]
                                << kernel_3[((kernel_row << 1) + kernel_row) + kernel_column]
                            );

                        convoluted_green =
                            convoluted_green
                            + (
                                pixel_buffer_green[
                                    buf_phys_idx(
                                        buffer_head,
                                        (kernel_row << IMAGE_DIM_BS) + kernel_column
                                    )
                                ]
                                << kernel_3[((kernel_row << 1) + kernel_row) + kernel_column]
                            );

                        convoluted_blue =
                            convoluted_blue
                            + (
                                pixel_buffer_blue[
                                    buf_phys_idx(
                                        buffer_head,
                                        (kernel_row << IMAGE_DIM_BS) + kernel_column
                                    )
                                ]
                                << kernel_3[((kernel_row << 1) + kernel_row) + kernel_column]
                            );
                    end
                end

                // Use the registered previous-cycle flag, matching the original.
                if (next_is_convolved_flag) begin
                    pixel_out_red   <= (convoluted_red   << 3);
                    pixel_out_green <= (convoluted_green << 3);
                    pixel_out_blue  <= (convoluted_blue  << 3);
                end
                else begin
                    pixel_out_red   <= (pixel_buffer_red  [buf_phys_idx(buffer_head, RAW_TAP_3)] << 7);
                    pixel_out_green <= (pixel_buffer_green[buf_phys_idx(buffer_head, RAW_TAP_3)] << 7);
                    pixel_out_blue  <= (pixel_buffer_blue [buf_phys_idx(buffer_head, RAW_TAP_3)] << 7);
                end
            end

            // ----------------------------------------------------
            // 5x5 blur
            // ----------------------------------------------------
            2'b10 : begin
                // Decide whether NEXT output should be convolved.
                if ((row_out_count < 2)
                    || (row_out_count >= IMAGE_DIM-2)
                    || ((row_out_count == IMAGE_DIM-3) && (column_out_count == IMAGE_DIM-1))
                    || (column_out_count >= IMAGE_DIM-4)) begin
                    next_is_convolved_flag <= 0;
                end
                else begin
                    next_is_convolved_flag <= 1;
                end

                // Convolve from logical 5x5 window taps.
                for (int kernel_row = 0; kernel_row < 5; kernel_row++) begin
                    for (int kernel_column = 0; kernel_column < 5; kernel_column++) begin
                        convoluted_red =
                            convoluted_red
                            + (
                                pixel_buffer_red[
                                    buf_phys_idx(
                                        buffer_head,
                                        (kernel_row << IMAGE_DIM_BS) + kernel_column
                                    )
                                ]
                                << kernel_5[((kernel_row << 2) + kernel_row) + kernel_column]
                            );

                        convoluted_green =
                            convoluted_green
                            + (
                                pixel_buffer_green[
                                    buf_phys_idx(
                                        buffer_head,
                                        (kernel_row << IMAGE_DIM_BS) + kernel_column
                                    )
                                ]
                                << kernel_5[((kernel_row << 2) + kernel_row) + kernel_column]
                            );

                        convoluted_blue =
                            convoluted_blue
                            + (
                                pixel_buffer_blue[
                                    buf_phys_idx(
                                        buffer_head,
                                        (kernel_row << IMAGE_DIM_BS) + kernel_column
                                    )
                                ]
                                << kernel_5[((kernel_row << 2) + kernel_row) + kernel_column]
                            );
                    end
                end

                // Use the registered previous-cycle flag, matching the original.
                if (next_is_convolved_flag) begin
                    pixel_out_red   <= (convoluted_red   << 1);
                    pixel_out_green <= (convoluted_green << 1);
                    pixel_out_blue  <= (convoluted_blue  << 1);
                end
                else begin
                    pixel_out_red   <= (pixel_buffer_red  [buf_phys_idx(buffer_head, RAW_TAP_5)] << 7);
                    pixel_out_green <= (pixel_buffer_green[buf_phys_idx(buffer_head, RAW_TAP_5)] << 7);
                    pixel_out_blue  <= (pixel_buffer_blue [buf_phys_idx(buffer_head, RAW_TAP_5)] << 7);
                end
            end

            // ----------------------------------------------------
            // 7x7 blur
            // ----------------------------------------------------
            2'b11 : begin
                // Decide whether NEXT output should be convolved.
                if ((row_out_count < 3)
                    || (row_out_count >= IMAGE_DIM-3)
                    || ((row_out_count == IMAGE_DIM-4) && (column_out_count == IMAGE_DIM-1))
                    || (column_out_count >= IMAGE_DIM-5)
                    || (column_out_count == 0)) begin
                    next_is_convolved_flag <= 0;
                end
                else begin
                    next_is_convolved_flag <= 1;
                end

                // Convolve from logical 7x7 window taps.
                for (int kernel_row = 0; kernel_row < 7; kernel_row++) begin
                    for (int kernel_column = 0; kernel_column < 7; kernel_column++) begin
                        convoluted_red =
                            convoluted_red
                            + (
                                pixel_buffer_red[
                                    buf_phys_idx(
                                        buffer_head,
                                        (kernel_row << IMAGE_DIM_BS) + kernel_column
                                    )
                                ]
                                << kernel_7[((kernel_row << 3) - kernel_row) + kernel_column]
                            );

                        convoluted_green =
                            convoluted_green
                            + (
                                pixel_buffer_green[
                                    buf_phys_idx(
                                        buffer_head,
                                        (kernel_row << IMAGE_DIM_BS) + kernel_column
                                    )
                                ]
                                << kernel_7[((kernel_row << 3) - kernel_row) + kernel_column]
                            );

                        convoluted_blue =
                            convoluted_blue
                            + (
                                pixel_buffer_blue[
                                    buf_phys_idx(
                                        buffer_head,
                                        (kernel_row << IMAGE_DIM_BS) + kernel_column
                                    )
                                ]
                                << kernel_7[((kernel_row << 3) - kernel_row) + kernel_column]
                            );
                    end
                end

                // Use the registered previous-cycle flag, matching the original.
                if (next_is_convolved_flag) begin
                    pixel_out_red   <= convoluted_red;
                    pixel_out_green <= convoluted_green;
                    pixel_out_blue  <= convoluted_blue;
                end
                else begin
                    pixel_out_red   <= (pixel_buffer_red  [buf_phys_idx(buffer_head, RAW_TAP_7)] << 7);
                    pixel_out_green <= (pixel_buffer_green[buf_phys_idx(buffer_head, RAW_TAP_7)] << 7);
                    pixel_out_blue  <= (pixel_buffer_blue [buf_phys_idx(buffer_head, RAW_TAP_7)] << 7);
                end
            end
        endcase

        // --------------------------------------------------------
        // Delayed framing / validity logic for blurred modes
        // --------------------------------------------------------
        if (kernel_size != 2'b00) begin
            // Output pixel is valid once startup lag has filled, or while
            // flushing the delayed tail after EOC.
            pixel_valid_out <= (
                (soc_lag_flag && pixel_valid_in)
                || (eoc_lag_flag && (((row_in_count == 0) && (column_in_count == 0)) || pixel_valid_in))
            );

            // Delayed SOC pulse.
            soc_out <= (
                (soc_lag_flag && pixel_valid_in)
                && soc_out_pulse
            );

            // Delayed EOC pulse.
            eoc_out <= (
                eoc_lag_flag
                && eoc_out_pulse
                && (((column_in_count != 0) && pixel_valid_in) || (column_in_count == 0))
            );

            // Delayed SOLF / EOLF pulses.
            solf_out <= (
                next_soc_is_solf
                && (soc_lag_flag && pixel_valid_in)
                && soc_out_pulse
            );

            eolf_out <= (
                next_eoc_is_eolf
                && eoc_lag_flag
                && eoc_out_pulse
            );

            // Reset output counters when delayed capture completes.
            if (eoc_out) begin
                row_out_count    <= 0;
                column_out_count <= 0;
            end

            // Advance output row / column counters whenever a delayed output pixel
            // is produced.
            if (
                (soc_lag_flag && pixel_valid_in && (!soc_out_pulse))
                || (eoc_lag_flag && (((row_in_count == 0) && (column_in_count == 0)) || pixel_valid_in))
            ) begin
                if (column_out_count == IMAGE_DIM-1) begin
                    column_out_count <= 0;
                    row_out_count    <= row_out_count + $bits(row_out_count)'(1);
                end
                else begin
                    column_out_count <= column_out_count + $bits(column_out_count)'(1);
                end
            end
        end
    end

endmodule