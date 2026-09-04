cuda_tile.module @m {
  entry @mha_scores(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8, %9 = get_tile_block_id : tile<i32>
    %10 = constant <i32: 32> : tile<i32>
    %11 = muli %9, %10 : tile<i32>
    %12 = constant <i32: 2048> : tile<i32>
    %13 = muli %1, %12 : tile<i32>
    %14 = addi %13, %11 : tile<i32>
    %15 = reshape %14 : tile<i32> -> tile<1x1xi32>
    %16 = broadcast %15 : tile<1x1xi32> -> tile<32x32xi32>
    %17 = iota : tile<32xi32>
    %18 = reshape %17 : tile<32xi32> -> tile<32x1xi32>
    %19 = broadcast %18 : tile<32x1xi32> -> tile<32x32xi32>
    %20 = constant <i32: 64> : tile<32x32xi32>
    %21 = muli %19, %20 : tile<32x32xi32>
    %22 = addi %16, %21 : tile<32x32xi32>
    %23 = iota : tile<32xi32>
    %24 = reshape %23 : tile<32xi32> -> tile<1x32xi32>
    %25 = broadcast %24 : tile<1x32xi32> -> tile<32x32xi32>
    %26 = addi %22, %25 : tile<32x32xi32>
    %27 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %28 = broadcast %27 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %29 = offset %28, %26 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %30, %31 = load_ptr_tko weak %29 token=%0 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
    %32 = constant <i32: 2048> : tile<i32>
    %33 = muli %5, %32 : tile<i32>
    %34 = addi %33, %11 : tile<i32>
    %35 = reshape %34 : tile<i32> -> tile<1x1xi32>
    %36 = broadcast %35 : tile<1x1xi32> -> tile<32x32xi32>
    %37 = iota : tile<32xi32>
    %38 = reshape %37 : tile<32xi32> -> tile<32x1xi32>
    %39 = broadcast %38 : tile<32x1xi32> -> tile<32x32xi32>
    %40 = addi %36, %39 : tile<32x32xi32>
    %41 = iota : tile<32xi32>
    %42 = reshape %41 : tile<32xi32> -> tile<1x32xi32>
    %43 = broadcast %42 : tile<1x32xi32> -> tile<32x32xi32>
    %44 = constant <i32: 64> : tile<32x32xi32>
    %45 = muli %43, %44 : tile<32x32xi32>
    %46 = addi %40, %45 : tile<32x32xi32>
    %47 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %48 = broadcast %47 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %49 = offset %48, %46 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %50, %51 = load_ptr_tko weak %49 token=%31 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
    %52 = constant <f64: 0.0> : tile<32x32xf64>
    %53 = mmaf %30, %50, %52 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
    %54 = constant <i32: 4096> : tile<i32>
    %55 = muli %9, %54 : tile<i32>
    %56 = constant <i32: 2048> : tile<i32>
    %57 = muli %1, %56 : tile<i32>
    %58 = addi %55, %57 : tile<i32>
    %59 = constant <i32: 32> : tile<i32>
    %60 = muli %5, %59 : tile<i32>
    %61 = addi %58, %60 : tile<i32>
    %62 = constant <f64: 0.17677669529663687> : tile<32x32xf64>
    %63 = mulf %53, %62 rounding<nearest_even> : tile<32x32xf64>
    %64 = reshape %61 : tile<i32> -> tile<1x1xi32>
    %65 = broadcast %64 : tile<1x1xi32> -> tile<32x32xi32>
    %66 = iota : tile<32xi32>
    %67 = reshape %66 : tile<32xi32> -> tile<32x1xi32>
    %68 = broadcast %67 : tile<32x1xi32> -> tile<32x32xi32>
    %69 = constant <i32: 64> : tile<32x32xi32>
    %70 = muli %68, %69 : tile<32x32xi32>
    %71 = addi %65, %70 : tile<32x32xi32>
    %72 = iota : tile<32xi32>
    %73 = reshape %72 : tile<32xi32> -> tile<1x32xi32>
    %74 = broadcast %73 : tile<1x32xi32> -> tile<32x32xi32>
    %75 = addi %71, %74 : tile<32x32xi32>
    %76 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %77 = broadcast %76 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %78 = offset %77, %75 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %79 = store_ptr_tko weak %78, %63 token=%51 : tile<32x32xptr<f64>>, tile<32x32xf64> -> token
    return
  }
}
