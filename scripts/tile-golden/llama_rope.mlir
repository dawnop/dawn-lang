cuda_tile.module @m {
  entry @llama_rope(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 2048> : tile<i32>
    %5 = muli %2, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1x1xi32>
    %7 = broadcast %6 : tile<1x1xi32> -> tile<64x16xi32>
    %8 = iota : tile<64xi32>
    %9 = reshape %8 : tile<64xi32> -> tile<64x1xi32>
    %10 = broadcast %9 : tile<64x1xi32> -> tile<64x16xi32>
    %11 = constant <i32: 32> : tile<64x16xi32>
    %12 = muli %10, %11 : tile<64x16xi32>
    %13 = addi %7, %12 : tile<64x16xi32>
    %14 = iota : tile<16xi32>
    %15 = reshape %14 : tile<16xi32> -> tile<1x16xi32>
    %16 = broadcast %15 : tile<1x16xi32> -> tile<64x16xi32>
    %17 = addi %13, %16 : tile<64x16xi32>
    %18 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %19 = broadcast %18 : tile<1x1xptr<f64>> -> tile<64x16xptr<f64>>
    %20 = offset %19, %17 : tile<64x16xptr<f64>>, tile<64x16xi32> -> tile<64x16xptr<f64>>
    %21, %22 = load_ptr_tko weak %20 token=%0 : tile<64x16xptr<f64>> -> tile<64x16xf64>, token
    %23 = constant <i32: 16> : tile<i32>
    %24 = addi %5, %23 : tile<i32>
    %25 = reshape %24 : tile<i32> -> tile<1x1xi32>
    %26 = broadcast %25 : tile<1x1xi32> -> tile<64x16xi32>
    %27 = iota : tile<64xi32>
    %28 = reshape %27 : tile<64xi32> -> tile<64x1xi32>
    %29 = broadcast %28 : tile<64x1xi32> -> tile<64x16xi32>
    %30 = constant <i32: 32> : tile<64x16xi32>
    %31 = muli %29, %30 : tile<64x16xi32>
    %32 = addi %26, %31 : tile<64x16xi32>
    %33 = iota : tile<16xi32>
    %34 = reshape %33 : tile<16xi32> -> tile<1x16xi32>
    %35 = broadcast %34 : tile<1x16xi32> -> tile<64x16xi32>
    %36 = addi %32, %35 : tile<64x16xi32>
    %37 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %38 = broadcast %37 : tile<1x1xptr<f64>> -> tile<64x16xptr<f64>>
    %39 = offset %38, %36 : tile<64x16xptr<f64>>, tile<64x16xi32> -> tile<64x16xptr<f64>>
    %40, %41 = load_ptr_tko weak %39 token=%22 : tile<64x16xptr<f64>> -> tile<64x16xf64>, token
    %42 = constant <i32: 0> : tile<i32>
    %43 = reshape %42 : tile<i32> -> tile<1x1xi32>
    %44 = broadcast %43 : tile<1x1xi32> -> tile<64x16xi32>
    %45 = iota : tile<64xi32>
    %46 = reshape %45 : tile<64xi32> -> tile<64x1xi32>
    %47 = broadcast %46 : tile<64x1xi32> -> tile<64x16xi32>
    %48 = constant <i32: 16> : tile<64x16xi32>
    %49 = muli %47, %48 : tile<64x16xi32>
    %50 = addi %44, %49 : tile<64x16xi32>
    %51 = iota : tile<16xi32>
    %52 = reshape %51 : tile<16xi32> -> tile<1x16xi32>
    %53 = broadcast %52 : tile<1x16xi32> -> tile<64x16xi32>
    %54 = addi %50, %53 : tile<64x16xi32>
    %55 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %56 = broadcast %55 : tile<1x1xptr<f64>> -> tile<64x16xptr<f64>>
    %57 = offset %56, %54 : tile<64x16xptr<f64>>, tile<64x16xi32> -> tile<64x16xptr<f64>>
    %58, %59 = load_ptr_tko weak %57 token=%41 : tile<64x16xptr<f64>> -> tile<64x16xf64>, token
    %60 = constant <i32: 0> : tile<i32>
    %61 = reshape %60 : tile<i32> -> tile<1x1xi32>
    %62 = broadcast %61 : tile<1x1xi32> -> tile<64x16xi32>
    %63 = iota : tile<64xi32>
    %64 = reshape %63 : tile<64xi32> -> tile<64x1xi32>
    %65 = broadcast %64 : tile<64x1xi32> -> tile<64x16xi32>
    %66 = constant <i32: 16> : tile<64x16xi32>
    %67 = muli %65, %66 : tile<64x16xi32>
    %68 = addi %62, %67 : tile<64x16xi32>
    %69 = iota : tile<16xi32>
    %70 = reshape %69 : tile<16xi32> -> tile<1x16xi32>
    %71 = broadcast %70 : tile<1x16xi32> -> tile<64x16xi32>
    %72 = addi %68, %71 : tile<64x16xi32>
    %73 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %74 = broadcast %73 : tile<1x1xptr<f64>> -> tile<64x16xptr<f64>>
    %75 = offset %74, %72 : tile<64x16xptr<f64>>, tile<64x16xi32> -> tile<64x16xptr<f64>>
    %76, %77 = load_ptr_tko weak %75 token=%59 : tile<64x16xptr<f64>> -> tile<64x16xf64>, token
    %78 = mulf %21, %58 rounding<nearest_even> : tile<64x16xf64>
    %79 = mulf %40, %76 rounding<nearest_even> : tile<64x16xf64>
    %80 = subf %78, %79 rounding<nearest_even> : tile<64x16xf64>
    %81 = reshape %arg3 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %82 = broadcast %81 : tile<1x1xptr<f64>> -> tile<64x16xptr<f64>>
    %83 = offset %82, %17 : tile<64x16xptr<f64>>, tile<64x16xi32> -> tile<64x16xptr<f64>>
    %84 = store_ptr_tko weak %83, %80 token=%77 : tile<64x16xptr<f64>>, tile<64x16xf64> -> token
    %85 = constant <i32: 16> : tile<i32>
    %86 = addi %5, %85 : tile<i32>
    %87 = mulf %21, %76 rounding<nearest_even> : tile<64x16xf64>
    %88 = mulf %40, %58 rounding<nearest_even> : tile<64x16xf64>
    %89 = addf %87, %88 rounding<nearest_even> : tile<64x16xf64>
    %90 = reshape %86 : tile<i32> -> tile<1x1xi32>
    %91 = broadcast %90 : tile<1x1xi32> -> tile<64x16xi32>
    %92 = iota : tile<64xi32>
    %93 = reshape %92 : tile<64xi32> -> tile<64x1xi32>
    %94 = broadcast %93 : tile<64x1xi32> -> tile<64x16xi32>
    %95 = constant <i32: 32> : tile<64x16xi32>
    %96 = muli %94, %95 : tile<64x16xi32>
    %97 = addi %91, %96 : tile<64x16xi32>
    %98 = iota : tile<16xi32>
    %99 = reshape %98 : tile<16xi32> -> tile<1x16xi32>
    %100 = broadcast %99 : tile<1x16xi32> -> tile<64x16xi32>
    %101 = addi %97, %100 : tile<64x16xi32>
    %102 = reshape %arg3 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %103 = broadcast %102 : tile<1x1xptr<f64>> -> tile<64x16xptr<f64>>
    %104 = offset %103, %101 : tile<64x16xptr<f64>>, tile<64x16xi32> -> tile<64x16xptr<f64>>
    %105 = store_ptr_tko weak %104, %89 token=%84 : tile<64x16xptr<f64>>, tile<64x16xf64> -> token
    return
  }
}
