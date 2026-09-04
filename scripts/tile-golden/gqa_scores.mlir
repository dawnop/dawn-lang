cuda_tile.module @m {
  entry @gqa_scores(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7 = constant <i32: 2> : tile<i32>
    %8 = muli %6, %7 : tile<i32>
    %9 = addi %8, %1 : tile<i32>
    %10 = constant <i32: 2048> : tile<i32>
    %11 = muli %9, %10 : tile<i32>
    %12 = reshape %11 : tile<i32> -> tile<1x1xi32>
    %13 = broadcast %12 : tile<1x1xi32> -> tile<64x32xi32>
    %14 = iota : tile<64xi32>
    %15 = reshape %14 : tile<64xi32> -> tile<64x1xi32>
    %16 = broadcast %15 : tile<64x1xi32> -> tile<64x32xi32>
    %17 = constant <i32: 32> : tile<64x32xi32>
    %18 = muli %16, %17 : tile<64x32xi32>
    %19 = addi %13, %18 : tile<64x32xi32>
    %20 = iota : tile<32xi32>
    %21 = reshape %20 : tile<32xi32> -> tile<1x32xi32>
    %22 = broadcast %21 : tile<1x32xi32> -> tile<64x32xi32>
    %23 = addi %19, %22 : tile<64x32xi32>
    %24 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %25 = broadcast %24 : tile<1x1xptr<f64>> -> tile<64x32xptr<f64>>
    %26 = offset %25, %23 : tile<64x32xptr<f64>>, tile<64x32xi32> -> tile<64x32xptr<f64>>
    %27, %28 = load_ptr_tko weak %26 token=%0 : tile<64x32xptr<f64>> -> tile<64x32xf64>, token
    %29 = constant <i32: 2048> : tile<i32>
    %30 = muli %6, %29 : tile<i32>
    %31 = reshape %30 : tile<i32> -> tile<1x1xi32>
    %32 = broadcast %31 : tile<1x1xi32> -> tile<32x64xi32>
    %33 = iota : tile<32xi32>
    %34 = reshape %33 : tile<32xi32> -> tile<32x1xi32>
    %35 = broadcast %34 : tile<32x1xi32> -> tile<32x64xi32>
    %36 = addi %32, %35 : tile<32x64xi32>
    %37 = iota : tile<64xi32>
    %38 = reshape %37 : tile<64xi32> -> tile<1x64xi32>
    %39 = broadcast %38 : tile<1x64xi32> -> tile<32x64xi32>
    %40 = constant <i32: 32> : tile<32x64xi32>
    %41 = muli %39, %40 : tile<32x64xi32>
    %42 = addi %36, %41 : tile<32x64xi32>
    %43 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %44 = broadcast %43 : tile<1x1xptr<f64>> -> tile<32x64xptr<f64>>
    %45 = offset %44, %42 : tile<32x64xptr<f64>>, tile<32x64xi32> -> tile<32x64xptr<f64>>
    %46, %47 = load_ptr_tko weak %45 token=%28 : tile<32x64xptr<f64>> -> tile<32x64xf64>, token
    %48 = constant <f64: 0.0> : tile<64x64xf64>
    %49 = mmaf %27, %46, %48 : tile<64x32xf64>, tile<32x64xf64>, tile<64x64xf64>
    %50 = constant <i32: 4096> : tile<i32>
    %51 = muli %9, %50 : tile<i32>
    %52 = constant <f64: 0.17677669529663687> : tile<64x64xf64>
    %53 = mulf %49, %52 rounding<nearest_even> : tile<64x64xf64>
    %54 = reshape %51 : tile<i32> -> tile<1x1xi32>
    %55 = broadcast %54 : tile<1x1xi32> -> tile<64x64xi32>
    %56 = iota : tile<64xi32>
    %57 = reshape %56 : tile<64xi32> -> tile<64x1xi32>
    %58 = broadcast %57 : tile<64x1xi32> -> tile<64x64xi32>
    %59 = constant <i32: 64> : tile<64x64xi32>
    %60 = muli %58, %59 : tile<64x64xi32>
    %61 = addi %55, %60 : tile<64x64xi32>
    %62 = iota : tile<64xi32>
    %63 = reshape %62 : tile<64xi32> -> tile<1x64xi32>
    %64 = broadcast %63 : tile<1x64xi32> -> tile<64x64xi32>
    %65 = addi %61, %64 : tile<64x64xi32>
    %66 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %67 = broadcast %66 : tile<1x1xptr<f64>> -> tile<64x64xptr<f64>>
    %68 = offset %67, %65 : tile<64x64xptr<f64>>, tile<64x64xi32> -> tile<64x64xptr<f64>>
    %69 = store_ptr_tko weak %68, %53 token=%47 : tile<64x64xptr<f64>>, tile<64x64xf64> -> token
    return
  }
}
