cuda_tile.module @m {
  entry @trig_sweep(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<128xi32>
    %8 = iota : tile<128xi32>
    %9 = addi %7, %8 : tile<128xi32>
    %10 = constant <i32: 500> : tile<128xi32>
    %11 = cmpi less_than %9, %10, signed : tile<128xi32> -> tile<128xi1>
    %12 = constant <f64: 0.0> : tile<128xf64>
    %13 = constant <f64: 1.0> : tile<128xf64>
    %14 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %15 = broadcast %14 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %16 = offset %15, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %17, %18 = load_ptr_tko weak %16, %11, %12 token=%0 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %19 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %20 = broadcast %19 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %21 = offset %20, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %22, %23 = load_ptr_tko weak %21, %11, %13 token=%18 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %24 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %25 = broadcast %24 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %26 = offset %25, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %27, %28 = load_ptr_tko weak %26, %11, %13 token=%23 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %29 = constant <i32: 0> : tile<i32>
    %30 = addi %5, %29 : tile<i32>
    %31 = sin %17 : tile<128xf64>
    %32 = reshape %30 : tile<i32> -> tile<1xi32>
    %33 = broadcast %32 : tile<1xi32> -> tile<128xi32>
    %34 = iota : tile<128xi32>
    %35 = addi %33, %34 : tile<128xi32>
    %36 = reshape %arg3 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %37 = broadcast %36 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %38 = offset %37, %35 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %39 = store_ptr_tko weak %38, %31, %11 token=%28 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    %40 = constant <i32: 500> : tile<i32>
    %41 = addi %5, %40 : tile<i32>
    %42 = cos %17 : tile<128xf64>
    %43 = reshape %41 : tile<i32> -> tile<1xi32>
    %44 = broadcast %43 : tile<1xi32> -> tile<128xi32>
    %45 = iota : tile<128xi32>
    %46 = addi %44, %45 : tile<128xi32>
    %47 = reshape %arg3 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %48 = broadcast %47 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %49 = offset %48, %46 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %50 = store_ptr_tko weak %49, %42, %11 token=%39 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    %51 = constant <i32: 1000> : tile<i32>
    %52 = addi %5, %51 : tile<i32>
    %53 = tan %17 : tile<128xf64>
    %54 = reshape %52 : tile<i32> -> tile<1xi32>
    %55 = broadcast %54 : tile<1xi32> -> tile<128xi32>
    %56 = iota : tile<128xi32>
    %57 = addi %55, %56 : tile<128xi32>
    %58 = reshape %arg3 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %59 = broadcast %58 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %60 = offset %59, %57 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %61 = store_ptr_tko weak %60, %53, %11 token=%50 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    %62 = constant <i32: 1500> : tile<i32>
    %63 = addi %5, %62 : tile<i32>
    %64 = sinh %17 : tile<128xf64>
    %65 = reshape %63 : tile<i32> -> tile<1xi32>
    %66 = broadcast %65 : tile<1xi32> -> tile<128xi32>
    %67 = iota : tile<128xi32>
    %68 = addi %66, %67 : tile<128xi32>
    %69 = reshape %arg3 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %70 = broadcast %69 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %71 = offset %70, %68 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %72 = store_ptr_tko weak %71, %64, %11 token=%61 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    %73 = constant <i32: 2000> : tile<i32>
    %74 = addi %5, %73 : tile<i32>
    %75 = cosh %17 : tile<128xf64>
    %76 = reshape %74 : tile<i32> -> tile<1xi32>
    %77 = broadcast %76 : tile<1xi32> -> tile<128xi32>
    %78 = iota : tile<128xi32>
    %79 = addi %77, %78 : tile<128xi32>
    %80 = reshape %arg3 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %81 = broadcast %80 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %82 = offset %81, %79 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %83 = store_ptr_tko weak %82, %75, %11 token=%72 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    %84 = constant <i32: 2500> : tile<i32>
    %85 = addi %5, %84 : tile<i32>
    %86 = atan2 %17, %22 : tile<128xf64>
    %87 = reshape %85 : tile<i32> -> tile<1xi32>
    %88 = broadcast %87 : tile<1xi32> -> tile<128xi32>
    %89 = iota : tile<128xi32>
    %90 = addi %88, %89 : tile<128xi32>
    %91 = reshape %arg3 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %92 = broadcast %91 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %93 = offset %92, %90 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %94 = store_ptr_tko weak %93, %86, %11 token=%83 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    %95 = constant <i32: 3000> : tile<i32>
    %96 = addi %5, %95 : tile<i32>
    %97 = remf %17, %27 : tile<128xf64>
    %98 = reshape %96 : tile<i32> -> tile<1xi32>
    %99 = broadcast %98 : tile<1xi32> -> tile<128xi32>
    %100 = iota : tile<128xi32>
    %101 = addi %99, %100 : tile<128xi32>
    %102 = reshape %arg3 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %103 = broadcast %102 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %104 = offset %103, %101 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %105 = store_ptr_tko weak %104, %97, %11 token=%94 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    return
  }
}
