module bit_shift_low_pass_filter #(
    parameter int unsigned IMAGE_DIM    = 64,
    parameter int unsigned IMAGE_DIM_BS = 6
)(
    input  wire         clk,
    input  wire         pixel_valid_in,
    input  wire         soc_in,
    input  wire         eoc_in,
    input  wire         solf_in,
    input  wire         eolf_in,
    input  wire  [7:0]  pixel_in,
    output logic        pixel_valid_out,
    output logic        soc_out,
    output logic        eoc_out,
    output logic        solf_out,
    output logic        eolf_out,
    output logic [14:0] pixel_out
);

    // -------------------------------------------------------------------------
    // 7x7 low-pass kernel
    // Sum = 128, so output remains unsigned Q8.7
    // -------------------------------------------------------------------------
    localparam logic [1:0] kernel_7 [0:48] = '{
        0, 0, 1, 1, 1, 0, 0,
        0, 1, 2, 2, 2, 1, 0,
        1, 2, 2, 2, 2, 2, 1,
        1, 2, 2, 2, 2, 2, 1,
        1, 2, 2, 2, 2, 2, 1,
        0, 1, 2, 2, 2, 1, 0,
        0, 0, 1, 1, 1, 0, 0
    };

    localparam int unsigned BUFFER_LAST     = (6 << IMAGE_DIM_BS) + 6;
    localparam int unsigned LAG_BUFFER_MAX  = BUFFER_LAST;
    localparam int unsigned LAG_BUFFER_SIZE = $clog2(LAG_BUFFER_MAX + 1);

    // -------------------------------------------------------------------------
    // LF flags
    // -------------------------------------------------------------------------
    logic next_soc_is_solf = 1'b0;
    logic next_eoc_is_eolf = 1'b0;

    // -------------------------------------------------------------------------
    // Pixel buffer
    // -------------------------------------------------------------------------
    (* ramstyle = "logic" *)
    (* altera_attribute = "-name AUTO_SHIFT_REGISTER_RECOGNITION OFF" *)
    logic [7:0] pixel_buffer [0:BUFFER_LAST];

    // -------------------------------------------------------------------------
    // Input counters and lag flags
    // -------------------------------------------------------------------------
    logic [IMAGE_DIM_BS-1:0] row_in_count    = '0;
    logic [IMAGE_DIM_BS-1:0] column_in_count = '0;

    logic [IMAGE_DIM_BS-1:0] row_out_count    = '0;
    logic [IMAGE_DIM_BS-1:0] column_out_count = '0;

    logic [LAG_BUFFER_SIZE-2:0] start_lag_buffer_count = '0;
    logic [LAG_BUFFER_SIZE-1:0] end_lag_buffer_count   = '0;

    logic soc_lag_flag  = 1'b0;
    logic eoc_lag_flag  = 1'b0;
    logic soc_out_pulse = 1'b0;
    logic eoc_out_pulse = 1'b0;

    // -------------------------------------------------------------------------
    // Stage-0 control signals
    // These preserve the original working logic semantics.
    // -------------------------------------------------------------------------
    logic output_valid_now;
    logic soc_now;
    logic eoc_now;
    logic solf_now;
    logic eolf_now;
    logic output_step_now;
    logic is_convolved_now;

    assign output_valid_now =
        ((soc_lag_flag && pixel_valid_in) ||
         (eoc_lag_flag && (((row_in_count == '0) && (column_in_count == '0)) || pixel_valid_in)));

    assign soc_now =
        ((soc_lag_flag && pixel_valid_in) && soc_out_pulse);

    assign eoc_now =
        ((eoc_lag_flag) &&
         (eoc_out_pulse) &&
         ((((column_in_count != '0) && pixel_valid_in) || (column_in_count == '0))));

    assign solf_now = (next_soc_is_solf && soc_now);
    assign eolf_now = (next_eoc_is_eolf && eoc_now);

    assign output_step_now =
        ((soc_lag_flag && pixel_valid_in && (!soc_out_pulse)) ||
         (eoc_lag_flag && (((row_in_count == '0) && (column_in_count == '0)) || pixel_valid_in)));

    assign is_convolved_now =
        !(
            (row_out_count < 3) ||
            (row_out_count >= IMAGE_DIM - 3) ||
            ((row_out_count == IMAGE_DIM - 4) && (column_out_count == IMAGE_DIM - 1)) ||
            (column_out_count >= IMAGE_DIM - 5) ||
            (column_out_count == '0)
         );

    // -------------------------------------------------------------------------
    // Stage 0 registered taps
    // -------------------------------------------------------------------------
    logic [14:0] tap_s0 [0:48];
    logic [14:0] raw_s0 = 15'd0;

    // -------------------------------------------------------------------------
    // Control / metadata pipes
    // Force these to remain ordinary FF chains, not altshift_taps.
    // -------------------------------------------------------------------------
    (* altera_attribute = "-name AUTO_SHIFT_REGISTER_RECOGNITION OFF" *) logic valid_pipe [0:5];
    (* altera_attribute = "-name AUTO_SHIFT_REGISTER_RECOGNITION OFF" *) logic soc_pipe   [0:5];
    (* altera_attribute = "-name AUTO_SHIFT_REGISTER_RECOGNITION OFF" *) logic eoc_pipe   [0:5];
    (* altera_attribute = "-name AUTO_SHIFT_REGISTER_RECOGNITION OFF" *) logic solf_pipe  [0:5];
    (* altera_attribute = "-name AUTO_SHIFT_REGISTER_RECOGNITION OFF" *) logic eolf_pipe  [0:5];
    (* altera_attribute = "-name AUTO_SHIFT_REGISTER_RECOGNITION OFF" *) logic conv_pipe  [0:5];

    // -------------------------------------------------------------------------
    // Reduction tree
    // 49 -> 25 -> 13 -> 7 -> 4 -> 2
    // -------------------------------------------------------------------------
    logic [15:0] sum_s1 [0:24];
    logic [16:0] sum_s2 [0:12];
    logic [17:0] sum_s3 [0:6];
    logic [18:0] sum_s4 [0:3];
    logic [19:0] sum_s5 [0:1];

    logic [14:0] raw_s1 = 15'd0;
    logic [14:0] raw_s2 = 15'd0;
    logic [14:0] raw_s3 = 15'd0;
    logic [14:0] raw_s4 = 15'd0;
    logic [14:0] raw_s5 = 15'd0;

    // Helper for final add to avoid truncation warning
    logic [20:0] conv_sum_s5;
    assign conv_sum_s5 = {1'b0, sum_s5[0]} + {1'b0, sum_s5[1]};

    integer idx;
    integer r_idx;
    integer c_idx;
    integer tap_idx;
    integer buf_idx;

    // -------------------------------------------------------------------------
    // Image buffer / lag logic
    // Preserves original working control semantics.
    // -------------------------------------------------------------------------
    always_ff @(posedge clk) begin : Image_Buffer
        if (soc_in) begin
            row_in_count           <= '0;
            column_in_count        <= '0;
            soc_lag_flag           <= 1'b0;
            start_lag_buffer_count <= {{(LAG_BUFFER_SIZE-2){1'b0}}, 1'b1};
        end

        if (eoc_in) begin
            eoc_lag_flag    <= 1'b1;
            row_in_count    <= '0;
            column_in_count <= '0;
        end

        if (soc_now) begin
            end_lag_buffer_count <= '0;
        end

        if (eolf_now) begin
            row_in_count           <= '0;
            column_in_count        <= '0;
            start_lag_buffer_count <= '0;
            end_lag_buffer_count   <= '0;
            soc_lag_flag           <= 1'b0;
            eoc_lag_flag           <= 1'b0;
            soc_out_pulse          <= 1'b0;
            eoc_out_pulse          <= 1'b0;
        end

        if (eoc_lag_flag && (((row_in_count == '0) && (column_in_count == '0)) || pixel_valid_in)) begin
            end_lag_buffer_count <= end_lag_buffer_count + {{(LAG_BUFFER_SIZE-1){1'b0}}, 1'b1};

            if (end_lag_buffer_count == (3 << IMAGE_DIM_BS) + 2) begin
                eoc_out_pulse <= 1'b1;
            end

            if (end_lag_buffer_count == (3 << IMAGE_DIM_BS) + 3) begin
                eoc_lag_flag <= 1'b0;
            end
        end

        if (pixel_valid_in || (eoc_lag_flag && (row_in_count == '0) && (column_in_count == '0))) begin
            for (idx = 0; idx < BUFFER_LAST; idx = idx + 1) begin
                pixel_buffer[idx] <= pixel_buffer[idx + 1];
            end

            if (pixel_valid_in) begin
                pixel_buffer[BUFFER_LAST] <= pixel_in;

                if (!soc_lag_flag) begin
                    start_lag_buffer_count <= start_lag_buffer_count + {{(LAG_BUFFER_SIZE-2){1'b0}}, 1'b1};

                    if (start_lag_buffer_count == (3 << IMAGE_DIM_BS) + 3) begin
                        soc_lag_flag  <= 1'b1;
                        soc_out_pulse <= 1'b1;
                    end
                end

                if (column_in_count == IMAGE_DIM - 1) begin
                    column_in_count <= '0;
                    row_in_count    <= row_in_count + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
                end
                else begin
                    column_in_count <= column_in_count + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
                end
            end
        end

        if (soc_out_pulse && pixel_valid_in) begin
            soc_out_pulse <= 1'b0;
        end

        if (eoc_out_pulse && ((((column_in_count != '0) && pixel_valid_in) || (column_in_count == '0)))) begin
            eoc_out_pulse <= 1'b0;
        end
    end

    // -------------------------------------------------------------------------
    // Main pipeline
    // -------------------------------------------------------------------------
    always_ff @(posedge clk) begin : Convolution_Pipeline
        if (solf_in) begin
            next_soc_is_solf <= 1'b1;
        end

        if (eolf_in) begin
            next_eoc_is_eolf <= 1'b1;
        end

        if (solf_now) begin
            next_soc_is_solf <= 1'b0;
        end

        if (eolf_now) begin
            next_eoc_is_eolf <= 1'b0;
        end

        // Stage 0
        valid_pipe[0] <= output_valid_now;
        soc_pipe[0]   <= soc_now;
        eoc_pipe[0]   <= eoc_now;
        solf_pipe[0]  <= solf_now;
        eolf_pipe[0]  <= eolf_now;
        conv_pipe[0]  <= is_convolved_now;

        raw_s0 <= {pixel_buffer[(3 << IMAGE_DIM_BS) + 3], 7'd0};

        for (r_idx = 0; r_idx < 7; r_idx = r_idx + 1) begin
            for (c_idx = 0; c_idx < 7; c_idx = c_idx + 1) begin
                tap_idx = ((r_idx << 3) - r_idx) + c_idx;
                buf_idx = (r_idx << IMAGE_DIM_BS) + c_idx;

                case (kernel_7[tap_idx])
                    2'd0: tap_s0[tap_idx] <= {7'd0, pixel_buffer[buf_idx]};
                    2'd1: tap_s0[tap_idx] <= {6'd0, pixel_buffer[buf_idx], 1'b0};
                    2'd2: tap_s0[tap_idx] <= {5'd0, pixel_buffer[buf_idx], 2'b00};
                    default: tap_s0[tap_idx] <= 15'd0;
                endcase
            end
        end

        // Stage 1
        valid_pipe[1] <= valid_pipe[0];
        soc_pipe[1]   <= soc_pipe[0];
        eoc_pipe[1]   <= eoc_pipe[0];
        solf_pipe[1]  <= solf_pipe[0];
        eolf_pipe[1]  <= eolf_pipe[0];
        conv_pipe[1]  <= conv_pipe[0];
        raw_s1        <= raw_s0;

        for (idx = 0; idx < 24; idx = idx + 1) begin
            sum_s1[idx] <= {1'b0, tap_s0[(idx << 1)]} + {1'b0, tap_s0[(idx << 1) + 1]};
        end
        sum_s1[24] <= {1'b0, tap_s0[48]};

        // Stage 2
        valid_pipe[2] <= valid_pipe[1];
        soc_pipe[2]   <= soc_pipe[1];
        eoc_pipe[2]   <= eoc_pipe[1];
        solf_pipe[2]  <= solf_pipe[1];
        eolf_pipe[2]  <= eolf_pipe[1];
        conv_pipe[2]  <= conv_pipe[1];
        raw_s2        <= raw_s1;

        for (idx = 0; idx < 12; idx = idx + 1) begin
            sum_s2[idx] <= {1'b0, sum_s1[(idx << 1)]} + {1'b0, sum_s1[(idx << 1) + 1]};
        end
        sum_s2[12] <= {1'b0, sum_s1[24]};

        // Stage 3
        valid_pipe[3] <= valid_pipe[2];
        soc_pipe[3]   <= soc_pipe[2];
        eoc_pipe[3]   <= eoc_pipe[2];
        solf_pipe[3]  <= solf_pipe[2];
        eolf_pipe[3]  <= eolf_pipe[2];
        conv_pipe[3]  <= conv_pipe[2];
        raw_s3        <= raw_s2;

        for (idx = 0; idx < 6; idx = idx + 1) begin
            sum_s3[idx] <= {1'b0, sum_s2[(idx << 1)]} + {1'b0, sum_s2[(idx << 1) + 1]};
        end
        sum_s3[6] <= {1'b0, sum_s2[12]};

        // Stage 4
        valid_pipe[4] <= valid_pipe[3];
        soc_pipe[4]   <= soc_pipe[3];
        eoc_pipe[4]   <= eoc_pipe[3];
        solf_pipe[4]  <= solf_pipe[3];
        eolf_pipe[4]  <= eolf_pipe[3];
        conv_pipe[4]  <= conv_pipe[3];
        raw_s4        <= raw_s3;

        for (idx = 0; idx < 3; idx = idx + 1) begin
            sum_s4[idx] <= {1'b0, sum_s3[(idx << 1)]} + {1'b0, sum_s3[(idx << 1) + 1]};
        end
        sum_s4[3] <= {1'b0, sum_s3[6]};

        // Stage 5
        valid_pipe[5] <= valid_pipe[4];
        soc_pipe[5]   <= soc_pipe[4];
        eoc_pipe[5]   <= eoc_pipe[4];
        solf_pipe[5]  <= solf_pipe[4];
        eolf_pipe[5]  <= eolf_pipe[4];
        conv_pipe[5]  <= conv_pipe[4];
        raw_s5        <= raw_s4;

        sum_s5[0] <= {1'b0, sum_s4[0]} + {1'b0, sum_s4[1]};
        sum_s5[1] <= {1'b0, sum_s4[2]} + {1'b0, sum_s4[3]};

        // Final output
        pixel_valid_out <= valid_pipe[5];
        soc_out         <= soc_pipe[5];
        eoc_out         <= eoc_pipe[5];
        solf_out        <= solf_pipe[5];
        eolf_out        <= eolf_pipe[5];

        if (conv_pipe[5]) begin
            if (conv_sum_s5 > 21'd32767) begin
                pixel_out <= 15'h7FFF;
            end
            else begin
                pixel_out <= conv_sum_s5[14:0];
            end
        end
        else begin
            pixel_out <= raw_s5;
        end

        // Coordinate tracking
        if (eoc_now) begin
            row_out_count    <= '0;
            column_out_count <= '0;
        end
        else if (output_step_now) begin
            if (column_out_count == IMAGE_DIM - 1) begin
                column_out_count <= '0;
                row_out_count    <= row_out_count + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
            end
            else begin
                column_out_count <= column_out_count + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
            end
        end
    end

endmodule