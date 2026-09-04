cuda_tile.module @m {
  entry @attn_scores(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7 = constant <i32: 1024> : tile<i32>
    %8 = muli %1, %7 : tile<i32>
    %9 = reshape %8 : tile<i32> -> tile<1x1xi32>
    %10 = broadcast %9 : tile<1x1xi32> -> tile<32x32xi32>
    %11 = iota : tile<32xi32>
    %12 = reshape %11 : tile<32xi32> -> tile<32x1xi32>
    %13 = broadcast %12 : tile<32x1xi32> -> tile<32x32xi32>
    %14 = constant <i32: 32> : tile<32x32xi32>
    %15 = muli %13, %14 : tile<32x32xi32>
    %16 = addi %10, %15 : tile<32x32xi32>
    %17 = iota : tile<32xi32>
    %18 = reshape %17 : tile<32xi32> -> tile<1x32xi32>
    %19 = broadcast %18 : tile<1x32xi32> -> tile<32x32xi32>
    %20 = addi %16, %19 : tile<32x32xi32>
    %21 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %22 = broadcast %21 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %23 = offset %22, %20 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %24, %25 = load_ptr_tko weak %23 token=%0 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
    %26 = constant <i32: 1024> : tile<i32>
    %27 = muli %5, %26 : tile<i32>
    %28 = reshape %27 : tile<i32> -> tile<1x1xi32>
    %29 = broadcast %28 : tile<1x1xi32> -> tile<32x32xi32>
    %30 = iota : tile<32xi32>
    %31 = reshape %30 : tile<32xi32> -> tile<32x1xi32>
    %32 = broadcast %31 : tile<32x1xi32> -> tile<32x32xi32>
    %33 = addi %29, %32 : tile<32x32xi32>
    %34 = iota : tile<32xi32>
    %35 = reshape %34 : tile<32xi32> -> tile<1x32xi32>
    %36 = broadcast %35 : tile<1x32xi32> -> tile<32x32xi32>
    %37 = constant <i32: 32> : tile<32x32xi32>
    %38 = muli %36, %37 : tile<32x32xi32>
    %39 = addi %33, %38 : tile<32x32xi32>
    %40 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %41 = broadcast %40 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %42 = offset %41, %39 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %43, %44 = load_ptr_tko weak %42 token=%25 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
    %45 = constant <f64: 0.0> : tile<32x32xf64>
    %46 = mmaf %24, %43, %45 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
    %47 = constant <i32: 2048> : tile<i32>
    %48 = muli %1, %47 : tile<i32>
    %49 = constant <i32: 32> : tile<i32>
    %50 = muli %5, %49 : tile<i32>
    %51 = addi %48, %50 : tile<i32>
    %52 = constant <f64: 0.17677669529663687> : tile<32x32xf64>
    %53 = mulf %46, %52 rounding<nearest_even> : tile<32x32xf64>
    %54 = reshape %51 : tile<i32> -> tile<1x1xi32>
    %55 = broadcast %54 : tile<1x1xi32> -> tile<32x32xi32>
    %56 = iota : tile<32xi32>
    %57 = reshape %56 : tile<32xi32> -> tile<32x1xi32>
    %58 = broadcast %57 : tile<32x1xi32> -> tile<32x32xi32>
    %59 = constant <i32: 64> : tile<32x32xi32>
    %60 = muli %58, %59 : tile<32x32xi32>
    %61 = addi %55, %60 : tile<32x32xi32>
    %62 = iota : tile<32xi32>
    %63 = reshape %62 : tile<32xi32> -> tile<1x32xi32>
    %64 = broadcast %63 : tile<1x32xi32> -> tile<32x32xi32>
    %65 = addi %61, %64 : tile<32x32xi32>
    %66 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %67 = broadcast %66 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %68 = offset %67, %65 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %69 = store_ptr_tko weak %68, %53 token=%44 : tile<32x32xptr<f64>>, tile<32x32xf64> -> token
    return
  }
}
