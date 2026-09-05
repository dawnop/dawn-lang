cuda_tile.module @m {
  entry @dtype_e8m0(%arg0: tile<ptr<f8E8M0FNU>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 0> : tile<i32>
    %7 = addi %5, %6 : tile<i32>
    %8 = reshape %5 : tile<i32> -> tile<1xi32>
    %9 = broadcast %8 : tile<1xi32> -> tile<128xi32>
    %10 = iota : tile<128xi32>
    %11 = addi %9, %10 : tile<128xi32>
    %12 = reshape %arg0 : tile<ptr<f8E8M0FNU>> -> tile<1xptr<f8E8M0FNU>>
    %13 = broadcast %12 : tile<1xptr<f8E8M0FNU>> -> tile<128xptr<f8E8M0FNU>>
    %14 = offset %13, %11 : tile<128xptr<f8E8M0FNU>>, tile<128xi32> -> tile<128xptr<f8E8M0FNU>>
    %15, %16 = load_ptr_tko weak %14 token=%0 : tile<128xptr<f8E8M0FNU>> -> tile<128xf8E8M0FNU>, token
    %17 = ftof %15 rounding<nearest_even> : tile<128xf8E8M0FNU> -> tile<128xf64>
    %18 = reshape %7 : tile<i32> -> tile<1xi32>
    %19 = broadcast %18 : tile<1xi32> -> tile<128xi32>
    %20 = iota : tile<128xi32>
    %21 = addi %19, %20 : tile<128xi32>
    %22 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %23 = broadcast %22 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %24 = offset %23, %21 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %25 = store_ptr_tko weak %24, %17 token=%16 : tile<128xptr<f64>>, tile<128xf64> -> token
    %26 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %27 = broadcast %26 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %28 = offset %27, %11 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %29, %30 = load_ptr_tko weak %28 token=%25 : tile<128xptr<f64>> -> tile<128xf64>, token
    %31 = ftof %29 rounding<nearest_even> : tile<128xf64> -> tile<128xf32>
    %32 = ftof %31 rounding<zero> : tile<128xf32> -> tile<128xf8E8M0FNU>
    %33 = constant <i32: 512> : tile<i32>
    %34 = addi %5, %33 : tile<i32>
    %35 = ftof %32 rounding<nearest_even> : tile<128xf8E8M0FNU> -> tile<128xf32>
    %36 = ftof %35 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %37 = reshape %34 : tile<i32> -> tile<1xi32>
    %38 = broadcast %37 : tile<1xi32> -> tile<128xi32>
    %39 = iota : tile<128xi32>
    %40 = addi %38, %39 : tile<128xi32>
    %41 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %42 = broadcast %41 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %43 = offset %42, %40 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %44 = store_ptr_tko weak %43, %36 token=%30 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
