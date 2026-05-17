module disparity_estimator #(
    parameter int unsigned IMAGE_DIM    = 128
)(
    input  wire                             clk,
    input  wire                             epi_valid_in,
    input  wire [14:0]                      epi_column_in [0:8],
    input  wire [$clog2(IMAGE_DIM)-1:0]     epi_column_idx_in,
    input  wire [$clog2(IMAGE_DIM)-1:0]     epi_idx_in,
    input  wire                             epi_orientation_in,
    input  wire                             angular_derivative_valid_in,
    input  wire signed [15:0]               angular_derivative_column_in [0:6],
    input  wire [$clog2(IMAGE_DIM)-1:0]     angular_derivative_row_idx_in,
    input  wire [$clog2(IMAGE_DIM)-1:0]     angular_derivative_column_idx_in,
    input  wire                             angular_derivative_orientation_in,
    output logic                            disparity_valid_out,
    output logic signed [31:0]              disparity_pixel_out,   // signed Q15.16
    output logic [$clog2(IMAGE_DIM)-1:0]    disparity_row_idx_out,
    output logic [$clog2(IMAGE_DIM)-1:0]    disparity_column_idx_out,
    output logic                            orientation_out
);

    // -------------------------------------------------------------------------
    // Divider configuration
    // -------------------------------------------------------------------------
    localparam int unsigned DIVIDEND_W      = 54;
    localparam int unsigned DIVISOR_W       = 38;
    localparam int unsigned QUOTIENT_W      = 54;
    localparam int unsigned DIV_ITERATIONS  = DIVIDEND_W;

    // -------------------------------------------------------------------------
    // Helper functions
    // -------------------------------------------------------------------------
    function automatic logic [37:0] abs38(input logic signed [37:0] x);
        begin
            if (x < 0) begin
                abs38 = $unsigned(-x);
            end
            else begin
                abs38 = $unsigned(x);
            end
        end
    endfunction

    function automatic logic signed [31:0] saturate_q15_16(
        input logic sign_bit,
        input logic [QUOTIENT_W-1:0] magnitude
    );
        logic signed [31:0] tmp32;
        begin
            if (sign_bit == 1'b0) begin
                if (magnitude > 54'd2147483647) begin
                    saturate_q15_16 = 32'sh7FFF_FFFF;
                end
                else begin
                    saturate_q15_16 = $signed(magnitude[31:0]);
                end
            end
            else begin
                if (magnitude >= 54'd2147483648) begin
                    saturate_q15_16 = 32'sh8000_0000;
                end
                else begin
                    tmp32 = $signed(magnitude[31:0]);
                    saturate_q15_16 = -tmp32;
                end
            end
        end
    endfunction

    function automatic logic signed [31:0] add_one_q15_16_sat(
        input logic signed [31:0] x
    );
        logic signed [32:0] tmp;
        begin
            tmp = $signed({x[31], x}) + 33'sd65536;

            if (tmp > 33'sd2147483647) begin
                add_one_q15_16_sat = 32'sh7FFF_FFFF;
            end
            else if (tmp < -33'sd2147483648) begin
                add_one_q15_16_sat = 32'sh8000_0000;
            end
            else begin
                add_one_q15_16_sat = tmp[31:0];
            end
        end
    endfunction

    // -------------------------------------------------------------------------
    // Delay variables
    // -------------------------------------------------------------------------
    logic signed [15:0] angular_derivative_column_in_d [0:6];
    logic signed [15:0] angular_derivative_column_in_2d [0:6];

    logic angular_derivative_orientation_in_d;
    logic angular_derivative_orientation_in_2d;

    logic angular_derivatives_valid_in_d;
    logic [$clog2(IMAGE_DIM)-1:0] angular_derivative_row_idx_in_d;
    logic [$clog2(IMAGE_DIM)-1:0] angular_derivative_column_idx_in_d;

    always_ff @(posedge clk) begin : Delays
        angular_derivative_column_in_d[0] <= angular_derivative_column_in[0];
        angular_derivative_column_in_d[1] <= angular_derivative_column_in[1];
        angular_derivative_column_in_d[2] <= angular_derivative_column_in[2];
        angular_derivative_column_in_d[3] <= angular_derivative_column_in[3];
        angular_derivative_column_in_d[4] <= angular_derivative_column_in[4];
        angular_derivative_column_in_d[5] <= angular_derivative_column_in[5];
        angular_derivative_column_in_d[6] <= angular_derivative_column_in[6];

        angular_derivative_orientation_in_d <= angular_derivative_orientation_in;

        angular_derivative_column_in_2d[0] <= angular_derivative_column_in_d[0];
        angular_derivative_column_in_2d[1] <= angular_derivative_column_in_d[1];
        angular_derivative_column_in_2d[2] <= angular_derivative_column_in_d[2];
        angular_derivative_column_in_2d[3] <= angular_derivative_column_in_d[3];
        angular_derivative_column_in_2d[4] <= angular_derivative_column_in_d[4];
        angular_derivative_column_in_2d[5] <= angular_derivative_column_in_d[5];
        angular_derivative_column_in_2d[6] <= angular_derivative_column_in_d[6];

        angular_derivative_orientation_in_2d <= angular_derivative_orientation_in_d;

        angular_derivatives_valid_in_d     <= angular_derivative_valid_in;
        angular_derivative_row_idx_in_d    <= angular_derivative_row_idx_in;
        angular_derivative_column_idx_in_d <= angular_derivative_column_idx_in;
    end

    // -------------------------------------------------------------------------
    // Spatial derivative computations
    // -------------------------------------------------------------------------
    logic [14:0] epi_column_in_nm3 [0:6];
    logic [14:0] epi_column_in_nm2 [0:6];
    logic [14:0] epi_column_in_nm1 [0:6];

    logic signed [15:0] spatial_derivatives [0:6];

    logic                         spatial_derivatives_valid      = 1'b0;
    logic [$clog2(IMAGE_DIM)-1:0] spatial_derivatives_row_idx    = '0;
    logic [$clog2(IMAGE_DIM)-1:0] spatial_derivatives_column_idx = '0;

    always_ff @(posedge clk) begin : Spatial_Derivative_Computations
        if (epi_valid_in) begin
            epi_column_in_nm1[0] <= epi_column_in[1];
            epi_column_in_nm1[1] <= epi_column_in[2];
            epi_column_in_nm1[2] <= epi_column_in[3];
            epi_column_in_nm1[3] <= epi_column_in[4];
            epi_column_in_nm1[4] <= epi_column_in[5];
            epi_column_in_nm1[5] <= epi_column_in[6];
            epi_column_in_nm1[6] <= epi_column_in[7];

            epi_column_in_nm2[0] <= epi_column_in_nm1[0];
            epi_column_in_nm2[1] <= epi_column_in_nm1[1];
            epi_column_in_nm2[2] <= epi_column_in_nm1[2];
            epi_column_in_nm2[3] <= epi_column_in_nm1[3];
            epi_column_in_nm2[4] <= epi_column_in_nm1[4];
            epi_column_in_nm2[5] <= epi_column_in_nm1[5];
            epi_column_in_nm2[6] <= epi_column_in_nm1[6];

            epi_column_in_nm3[0] <= epi_column_in_nm2[0];
            epi_column_in_nm3[1] <= epi_column_in_nm2[1];
            epi_column_in_nm3[2] <= epi_column_in_nm2[2];
            epi_column_in_nm3[3] <= epi_column_in_nm2[3];
            epi_column_in_nm3[4] <= epi_column_in_nm2[4];
            epi_column_in_nm3[5] <= epi_column_in_nm2[5];
            epi_column_in_nm3[6] <= epi_column_in_nm2[6];
        end

        spatial_derivatives[0] <= ($signed({1'b0, epi_column_in_nm1[0]}) - $signed({1'b0, epi_column_in_nm3[0]})) / 2;
        spatial_derivatives[1] <= ($signed({1'b0, epi_column_in_nm1[1]}) - $signed({1'b0, epi_column_in_nm3[1]})) / 2;
        spatial_derivatives[2] <= ($signed({1'b0, epi_column_in_nm1[2]}) - $signed({1'b0, epi_column_in_nm3[2]})) / 2;
        spatial_derivatives[3] <= ($signed({1'b0, epi_column_in_nm1[3]}) - $signed({1'b0, epi_column_in_nm3[3]})) / 2;
        spatial_derivatives[4] <= ($signed({1'b0, epi_column_in_nm1[4]}) - $signed({1'b0, epi_column_in_nm3[4]})) / 2;
        spatial_derivatives[5] <= ($signed({1'b0, epi_column_in_nm1[5]}) - $signed({1'b0, epi_column_in_nm3[5]})) / 2;
        spatial_derivatives[6] <= ($signed({1'b0, epi_column_in_nm1[6]}) - $signed({1'b0, epi_column_in_nm3[6]})) / 2;

        spatial_derivatives_valid      <= (angular_derivative_column_idx_in_d != 0) &&
                                          (angular_derivative_column_idx_in_d != IMAGE_DIM-1) &&
                                          angular_derivatives_valid_in_d;
        spatial_derivatives_row_idx    <= angular_derivative_row_idx_in_d;
        spatial_derivatives_column_idx <= angular_derivative_column_idx_in_d;
    end

    // -------------------------------------------------------------------------
    // Product stage
    // -------------------------------------------------------------------------
    logic signed [31:0] uv_0 = 0;
    logic signed [31:0] uv_1 = 0;
    logic signed [31:0] uv_2 = 0;
    logic signed [31:0] uv_3 = 0;
    logic signed [31:0] uv_4 = 0;
    logic signed [31:0] uv_5 = 0;
    logic signed [31:0] uv_6 = 0;

    logic signed [31:0] uu_0 = 0;
    logic signed [31:0] uu_1 = 0;
    logic signed [31:0] uu_2 = 0;
    logic signed [31:0] uu_3 = 0;
    logic signed [31:0] uu_4 = 0;
    logic signed [31:0] uu_5 = 0;
    logic signed [31:0] uu_6 = 0;

    logic                         prod_valid       = 1'b0;
    logic [$clog2(IMAGE_DIM)-1:0] prod_row_idx     = '0;
    logic [$clog2(IMAGE_DIM)-1:0] prod_column_idx  = '0;
    logic                         prod_orientation = 1'b0;

    always_ff @(posedge clk) begin : Product_Computations
        uv_0 <= angular_derivative_column_in_2d[0] * spatial_derivatives[0];
        uv_1 <= angular_derivative_column_in_2d[1] * spatial_derivatives[1];
        uv_2 <= angular_derivative_column_in_2d[2] * spatial_derivatives[2];
        uv_3 <= angular_derivative_column_in_2d[3] * spatial_derivatives[3];
        uv_4 <= angular_derivative_column_in_2d[4] * spatial_derivatives[4];
        uv_5 <= angular_derivative_column_in_2d[5] * spatial_derivatives[5];
        uv_6 <= angular_derivative_column_in_2d[6] * spatial_derivatives[6];

        uu_0 <= angular_derivative_column_in_2d[0] * angular_derivative_column_in_2d[0];
        uu_1 <= angular_derivative_column_in_2d[1] * angular_derivative_column_in_2d[1];
        uu_2 <= angular_derivative_column_in_2d[2] * angular_derivative_column_in_2d[2];
        uu_3 <= angular_derivative_column_in_2d[3] * angular_derivative_column_in_2d[3];
        uu_4 <= angular_derivative_column_in_2d[4] * angular_derivative_column_in_2d[4];
        uu_5 <= angular_derivative_column_in_2d[5] * angular_derivative_column_in_2d[5];
        uu_6 <= angular_derivative_column_in_2d[6] * angular_derivative_column_in_2d[6];

        prod_valid       <= spatial_derivatives_valid;
        prod_orientation <= angular_derivative_orientation_in_2d;

        if (angular_derivative_orientation_in_2d == 1'b0) begin
            prod_row_idx    <= spatial_derivatives_row_idx;
            prod_column_idx <= spatial_derivatives_column_idx;
        end
        else begin
            prod_row_idx    <= spatial_derivatives_column_idx;
            prod_column_idx <= spatial_derivatives_row_idx;
        end
    end

    // -------------------------------------------------------------------------
    // Fully pipelined adder tree
    // -------------------------------------------------------------------------
    logic signed [32:0] uv_s1_0 = 0;
    logic signed [32:0] uv_s1_1 = 0;
    logic signed [32:0] uv_s1_2 = 0;
    logic signed [32:0] uv_s1_3 = 0;

    logic signed [32:0] uu_s1_0 = 0;
    logic signed [32:0] uu_s1_1 = 0;
    logic signed [32:0] uu_s1_2 = 0;
    logic signed [32:0] uu_s1_3 = 0;

    logic                         sum1_valid       = 1'b0;
    logic [$clog2(IMAGE_DIM)-1:0] sum1_row_idx     = '0;
    logic [$clog2(IMAGE_DIM)-1:0] sum1_column_idx  = '0;
    logic                         sum1_orientation = 1'b0;

    always_ff @(posedge clk) begin : Sum_Tree_Stage1
        uv_s1_0 <= uv_0 + uv_1;
        uv_s1_1 <= uv_2 + uv_3;
        uv_s1_2 <= uv_4 + uv_5;
        uv_s1_3 <= uv_6;

        uu_s1_0 <= uu_0 + uu_1;
        uu_s1_1 <= uu_2 + uu_3;
        uu_s1_2 <= uu_4 + uu_5;
        uu_s1_3 <= uu_6;

        sum1_valid       <= prod_valid;
        sum1_row_idx     <= prod_row_idx;
        sum1_column_idx  <= prod_column_idx;
        sum1_orientation <= prod_orientation;
    end

    logic signed [33:0] uv_s2_0 = 0;
    logic signed [33:0] uv_s2_1 = 0;

    logic signed [33:0] uu_s2_0 = 0;
    logic signed [33:0] uu_s2_1 = 0;

    logic                         sum2_valid       = 1'b0;
    logic [$clog2(IMAGE_DIM)-1:0] sum2_row_idx     = '0;
    logic [$clog2(IMAGE_DIM)-1:0] sum2_column_idx  = '0;
    logic                         sum2_orientation = 1'b0;

    always_ff @(posedge clk) begin : Sum_Tree_Stage2
        uv_s2_0 <= uv_s1_0 + uv_s1_1;
        uv_s2_1 <= uv_s1_2 + uv_s1_3;

        uu_s2_0 <= uu_s1_0 + uu_s1_1;
        uu_s2_1 <= uu_s1_2 + uu_s1_3;

        sum2_valid       <= sum1_valid;
        sum2_row_idx     <= sum1_row_idx;
        sum2_column_idx  <= sum1_column_idx;
        sum2_orientation <= sum1_orientation;
    end

    logic signed [37:0] sum_uv = 0;
    logic signed [37:0] sum_uu = 0;

    logic                         sum_valid       = 1'b0;
    logic [$clog2(IMAGE_DIM)-1:0] sum_row_idx     = '0;
    logic [$clog2(IMAGE_DIM)-1:0] sum_column_idx  = '0;
    logic                         sum_orientation = 1'b0;

    always_ff @(posedge clk) begin : Sum_Tree_Stage3
        sum_uv <= $signed(uv_s2_0) + $signed(uv_s2_1);
        sum_uu <= $signed(uu_s2_0) + $signed(uu_s2_1);

        sum_valid       <= sum2_valid;
        sum_row_idx     <= sum2_row_idx;
        sum_column_idx  <= sum2_column_idx;
        sum_orientation <= sum2_orientation;
    end

    // -------------------------------------------------------------------------
    // 3-cycle-per-bit exact divider
    // Phase A: shift
    // Phase B: compare only
    // Phase C: subtract/select + quotient insert
    // -------------------------------------------------------------------------

    // State after each completed bit
    logic [DIVIDEND_W-1:0] dividend_state_pipe    [0:DIV_ITERATIONS];
    logic [DIVISOR_W-1:0]  divisor_state_pipe     [0:DIV_ITERATIONS];
    logic [DIVISOR_W:0]    remainder_state_pipe   [0:DIV_ITERATIONS];
    logic [QUOTIENT_W-1:0] quotient_state_pipe    [0:DIV_ITERATIONS];

    logic                  valid_state_pipe       [0:DIV_ITERATIONS];
    logic                  sign_state_pipe        [0:DIV_ITERATIONS];
    logic                  div_zero_state_pipe    [0:DIV_ITERATIONS];

    logic [$clog2(IMAGE_DIM)-1:0] row_idx_state_pipe      [0:DIV_ITERATIONS];
    logic [$clog2(IMAGE_DIM)-1:0] column_idx_state_pipe   [0:DIV_ITERATIONS];
    logic                         orientation_state_pipe  [0:DIV_ITERATIONS];

    // Phase A registers
    logic [DIVIDEND_W-1:0] dividend_shift_pipe   [0:DIV_ITERATIONS-1];
    logic [DIVISOR_W-1:0]  divisor_shift_pipe    [0:DIV_ITERATIONS-1];
    logic [DIVISOR_W:0]    remainder_shift_pipe  [0:DIV_ITERATIONS-1];
    logic [QUOTIENT_W-1:0] quotient_shift_pipe   [0:DIV_ITERATIONS-1];

    logic                  valid_shift_pipe      [0:DIV_ITERATIONS-1];
    logic                  sign_shift_pipe       [0:DIV_ITERATIONS-1];
    logic                  div_zero_shift_pipe   [0:DIV_ITERATIONS-1];

    logic [$clog2(IMAGE_DIM)-1:0] row_idx_shift_pipe      [0:DIV_ITERATIONS-1];
    logic [$clog2(IMAGE_DIM)-1:0] column_idx_shift_pipe   [0:DIV_ITERATIONS-1];
    logic                         orientation_shift_pipe  [0:DIV_ITERATIONS-1];

    // Phase B registers (compare-only stage)
    logic [DIVIDEND_W-1:0] dividend_cmp_pipe   [0:DIV_ITERATIONS-1];
    logic [DIVISOR_W-1:0]  divisor_cmp_pipe    [0:DIV_ITERATIONS-1];
    logic [DIVISOR_W:0]    remainder_cmp_pipe  [0:DIV_ITERATIONS-1];
    logic [QUOTIENT_W-1:0] quotient_cmp_pipe   [0:DIV_ITERATIONS-1];

    logic                  valid_cmp_pipe      [0:DIV_ITERATIONS-1];
    logic                  sign_cmp_pipe       [0:DIV_ITERATIONS-1];
    logic                  div_zero_cmp_pipe   [0:DIV_ITERATIONS-1];
    logic                  take_sub_cmp_pipe   [0:DIV_ITERATIONS-1];

    logic [$clog2(IMAGE_DIM)-1:0] row_idx_cmp_pipe      [0:DIV_ITERATIONS-1];
    logic [$clog2(IMAGE_DIM)-1:0] column_idx_cmp_pipe   [0:DIV_ITERATIONS-1];
    logic                         orientation_cmp_pipe  [0:DIV_ITERATIONS-1];

    // State load
    always_ff @(posedge clk) begin : Divider_State_Load
        valid_state_pipe[0]       <= sum_valid;
        sign_state_pipe[0]        <= sum_uv[37];
        div_zero_state_pipe[0]    <= (sum_uu == 0);
        row_idx_state_pipe[0]     <= sum_row_idx;
        column_idx_state_pipe[0]  <= sum_column_idx;
        orientation_state_pipe[0] <= sum_orientation;

        if (sum_valid && (sum_uu != 0)) begin
            dividend_state_pipe[0]  <= {abs38(sum_uv), 16'd0};
            divisor_state_pipe[0]   <= sum_uu[37:0];
            remainder_state_pipe[0] <= '0;
            quotient_state_pipe[0]  <= '0;
        end
        else begin
            dividend_state_pipe[0]  <= '0;
            divisor_state_pipe[0]   <= '0;
            remainder_state_pipe[0] <= '0;
            quotient_state_pipe[0]  <= '0;
        end
    end

    genvar s;
    generate
        for (s = 0; s < DIV_ITERATIONS; s = s + 1) begin : Divider_Pipeline

            // -------------------------------------------------------------
            // Phase A: shift only
            // -------------------------------------------------------------
            always_ff @(posedge clk) begin : Divider_Shift_Phase
                valid_shift_pipe[s]       <= valid_state_pipe[s];
                sign_shift_pipe[s]        <= sign_state_pipe[s];
                div_zero_shift_pipe[s]    <= div_zero_state_pipe[s];
                row_idx_shift_pipe[s]     <= row_idx_state_pipe[s];
                column_idx_shift_pipe[s]  <= column_idx_state_pipe[s];
                orientation_shift_pipe[s] <= orientation_state_pipe[s];

                divisor_shift_pipe[s]     <= divisor_state_pipe[s];
                quotient_shift_pipe[s]    <= quotient_state_pipe[s];

                if (!valid_state_pipe[s] || div_zero_state_pipe[s]) begin
                    dividend_shift_pipe[s]  <= '0;
                    remainder_shift_pipe[s] <= '0;
                end
                else begin
                    dividend_shift_pipe[s]  <= {dividend_state_pipe[s][DIVIDEND_W-2:0], 1'b0};
                    remainder_shift_pipe[s] <= {remainder_state_pipe[s][DIVISOR_W-1:0], dividend_state_pipe[s][DIVIDEND_W-1]};
                end
            end

            // -------------------------------------------------------------
            // Phase B: compare only
            // -------------------------------------------------------------
            always_ff @(posedge clk) begin : Divider_Compare_Phase
                valid_cmp_pipe[s]       <= valid_shift_pipe[s];
                sign_cmp_pipe[s]        <= sign_shift_pipe[s];
                div_zero_cmp_pipe[s]    <= div_zero_shift_pipe[s];
                row_idx_cmp_pipe[s]     <= row_idx_shift_pipe[s];
                column_idx_cmp_pipe[s]  <= column_idx_shift_pipe[s];
                orientation_cmp_pipe[s] <= orientation_shift_pipe[s];

                dividend_cmp_pipe[s]    <= dividend_shift_pipe[s];
                divisor_cmp_pipe[s]     <= divisor_shift_pipe[s];
                remainder_cmp_pipe[s]   <= remainder_shift_pipe[s];
                quotient_cmp_pipe[s]    <= quotient_shift_pipe[s];

                if (!valid_shift_pipe[s] || div_zero_shift_pipe[s]) begin
                    take_sub_cmp_pipe[s] <= 1'b0;
                end
                else begin
                    take_sub_cmp_pipe[s] <= (remainder_shift_pipe[s] >= {1'b0, divisor_shift_pipe[s]});
                end
            end

            // -------------------------------------------------------------
            // Phase C: subtract / select / quotient insert
            // -------------------------------------------------------------
            always_ff @(posedge clk) begin : Divider_Subtract_Phase
                valid_state_pipe[s+1]       <= valid_cmp_pipe[s];
                sign_state_pipe[s+1]        <= sign_cmp_pipe[s];
                div_zero_state_pipe[s+1]    <= div_zero_cmp_pipe[s];
                row_idx_state_pipe[s+1]     <= row_idx_cmp_pipe[s];
                column_idx_state_pipe[s+1]  <= column_idx_cmp_pipe[s];
                orientation_state_pipe[s+1] <= orientation_cmp_pipe[s];

                divisor_state_pipe[s+1]     <= divisor_cmp_pipe[s];
                dividend_state_pipe[s+1]    <= dividend_cmp_pipe[s];

                if (!valid_cmp_pipe[s] || div_zero_cmp_pipe[s]) begin
                    remainder_state_pipe[s+1] <= '0;
                    quotient_state_pipe[s+1]  <= '0;
                end
                else begin
                    if (take_sub_cmp_pipe[s]) begin
                        remainder_state_pipe[s+1] <= remainder_cmp_pipe[s] - {1'b0, divisor_cmp_pipe[s]};
                        quotient_state_pipe[s+1]  <= {quotient_cmp_pipe[s][QUOTIENT_W-2:0], 1'b1};
                    end
                    else begin
                        remainder_state_pipe[s+1] <= remainder_cmp_pipe[s];
                        quotient_state_pipe[s+1]  <= {quotient_cmp_pipe[s][QUOTIENT_W-2:0], 1'b0};
                    end
                end
            end
        end
    endgenerate

    // -------------------------------------------------------------------------
    // Output stage
    // -------------------------------------------------------------------------
    always_ff @(posedge clk) begin : Output_Stage
        disparity_valid_out      <= 1'b0;
        disparity_pixel_out      <= 32'sd0;
        disparity_row_idx_out    <= '0;
        disparity_column_idx_out <= '0;
        orientation_out          <= 1'b0;

        if (valid_state_pipe[DIV_ITERATIONS]) begin
            disparity_valid_out      <= 1'b1;
            disparity_row_idx_out    <= row_idx_state_pipe[DIV_ITERATIONS];
            disparity_column_idx_out <= column_idx_state_pipe[DIV_ITERATIONS];
            orientation_out          <= orientation_state_pipe[DIV_ITERATIONS];

            if (div_zero_state_pipe[DIV_ITERATIONS]) begin
                disparity_pixel_out <= 32'sd0;
            end
            else begin
                disparity_pixel_out <= add_one_q15_16_sat(
                    saturate_q15_16(
                        sign_state_pipe[DIV_ITERATIONS],
                        quotient_state_pipe[DIV_ITERATIONS]
                    )
                );
            end
        end
    end

endmodule