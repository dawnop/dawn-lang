cuda_tile.module @m {
  entry @dtype_e2m1(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 16> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 128> : tile<i32>
    %7 = muli %1, %6 : tile<i32>
    %8 = reshape %5 : tile<i32> -> tile<1xi32>
    %9 = broadcast %8 : tile<1xi32> -> tile<16xi32>
    %10 = iota : tile<16xi32>
    %11 = addi %9, %10 : tile<16xi32>
    %12 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %13 = broadcast %12 : tile<1xptr<i32>> -> tile<16xptr<i32>>
    %14 = offset %13, %11 : tile<16xptr<i32>>, tile<16xi32> -> tile<16xptr<i32>>
    %15, %16 = load_ptr_tko weak %14 token=%0 : tile<16xptr<i32>> -> tile<16xi32>, token
    %17 = pack %15 : tile<16xi32> -> tile<64xi8>
    %18 = unpack %17 : tile<64xi8> -> tile<128xf4E2M1FN>
    %19 = constant <i32: 0> : tile<i32>
    %20 = addi %7, %19 : tile<i32>
    %21 = ftof %18 rounding<nearest_even> : tile<128xf4E2M1FN> -> tile<128xf64>
    %22 = reshape %20 : tile<i32> -> tile<1xi32>
    %23 = broadcast %22 : tile<1xi32> -> tile<128xi32>
    %24 = iota : tile<128xi32>
    %25 = addi %23, %24 : tile<128xi32>
    %26 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %27 = broadcast %26 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %28 = offset %27, %25 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %29 = store_ptr_tko weak %28, %21 token=%16 : tile<128xptr<f64>>, tile<128xf64> -> token
    %30 = constant <i32: 512> : tile<i32>
    %31 = addi %7, %30 : tile<i32>
    %32 = reshape %7 : tile<i32> -> tile<1xi32>
    %33 = broadcast %32 : tile<1xi32> -> tile<128xi32>
    %34 = iota : tile<128xi32>
    %35 = addi %33, %34 : tile<128xi32>
    %36 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %37 = broadcast %36 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %38 = offset %37, %35 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %39, %40 = load_ptr_tko weak %38 token=%29 : tile<128xptr<f64>> -> tile<128xf64>, token
    %41 = ftof %39 rounding<nearest_even> : tile<128xf64> -> tile<128xf4E2M1FN>
    %42 = ftof %41 rounding<nearest_even> : tile<128xf4E2M1FN> -> tile<128xf64>
    %43 = reshape %31 : tile<i32> -> tile<1xi32>
    %44 = broadcast %43 : tile<1xi32> -> tile<128xi32>
    %45 = iota : tile<128xi32>
    %46 = addi %44, %45 : tile<128xi32>
    %47 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %48 = broadcast %47 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %49 = offset %48, %46 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %50 = store_ptr_tko weak %49, %42 token=%40 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
