cuda_tile.module @m {
  entry @mmaf_scaled_e4m3(%arg0: tile<ptr<f8E4M3FN>>, %arg1: tile<ptr<f8E4M3FN>>, %arg2: tile<ptr<f8E8M0FNU>>, %arg3: tile<ptr<f8E8M0FNU>>, %arg4: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = reshape %1 : tile<i32> -> tile<1x1xi32>
    %3 = broadcast %2 : tile<1x1xi32> -> tile<32x64xi32>
    %4 = iota : tile<32xi32>
    %5 = reshape %4 : tile<32xi32> -> tile<32x1xi32>
    %6 = broadcast %5 : tile<32x1xi32> -> tile<32x64xi32>
    %7 = constant <i32: 64> : tile<32x64xi32>
    %8 = muli %6, %7 : tile<32x64xi32>
    %9 = addi %3, %8 : tile<32x64xi32>
    %10 = iota : tile<64xi32>
    %11 = reshape %10 : tile<64xi32> -> tile<1x64xi32>
    %12 = broadcast %11 : tile<1x64xi32> -> tile<32x64xi32>
    %13 = addi %9, %12 : tile<32x64xi32>
    %14 = reshape %arg0 : tile<ptr<f8E4M3FN>> -> tile<1x1xptr<f8E4M3FN>>
    %15 = broadcast %14 : tile<1x1xptr<f8E4M3FN>> -> tile<32x64xptr<f8E4M3FN>>
    %16 = offset %15, %13 : tile<32x64xptr<f8E4M3FN>>, tile<32x64xi32> -> tile<32x64xptr<f8E4M3FN>>
    %17, %18 = load_ptr_tko weak %16 token=%0 : tile<32x64xptr<f8E4M3FN>> -> tile<32x64xf8E4M3FN>, token
    %19 = reshape %1 : tile<i32> -> tile<1x1xi32>
    %20 = broadcast %19 : tile<1x1xi32> -> tile<64x32xi32>
    %21 = iota : tile<64xi32>
    %22 = reshape %21 : tile<64xi32> -> tile<64x1xi32>
    %23 = broadcast %22 : tile<64x1xi32> -> tile<64x32xi32>
    %24 = constant <i32: 32> : tile<64x32xi32>
    %25 = muli %23, %24 : tile<64x32xi32>
    %26 = addi %20, %25 : tile<64x32xi32>
    %27 = iota : tile<32xi32>
    %28 = reshape %27 : tile<32xi32> -> tile<1x32xi32>
    %29 = broadcast %28 : tile<1x32xi32> -> tile<64x32xi32>
    %30 = addi %26, %29 : tile<64x32xi32>
    %31 = reshape %arg1 : tile<ptr<f8E4M3FN>> -> tile<1x1xptr<f8E4M3FN>>
    %32 = broadcast %31 : tile<1x1xptr<f8E4M3FN>> -> tile<64x32xptr<f8E4M3FN>>
    %33 = offset %32, %30 : tile<64x32xptr<f8E4M3FN>>, tile<64x32xi32> -> tile<64x32xptr<f8E4M3FN>>
    %34, %35 = load_ptr_tko weak %33 token=%18 : tile<64x32xptr<f8E4M3FN>> -> tile<64x32xf8E4M3FN>, token
    %36 = reshape %1 : tile<i32> -> tile<1x1xi32>
    %37 = broadcast %36 : tile<1x1xi32> -> tile<32x2xi32>
    %38 = iota : tile<32xi32>
    %39 = reshape %38 : tile<32xi32> -> tile<32x1xi32>
    %40 = broadcast %39 : tile<32x1xi32> -> tile<32x2xi32>
    %41 = constant <i32: 2> : tile<32x2xi32>
    %42 = muli %40, %41 : tile<32x2xi32>
    %43 = addi %37, %42 : tile<32x2xi32>
    %44 = iota : tile<2xi32>
    %45 = reshape %44 : tile<2xi32> -> tile<1x2xi32>
    %46 = broadcast %45 : tile<1x2xi32> -> tile<32x2xi32>
    %47 = addi %43, %46 : tile<32x2xi32>
    %48 = reshape %arg2 : tile<ptr<f8E8M0FNU>> -> tile<1x1xptr<f8E8M0FNU>>
    %49 = broadcast %48 : tile<1x1xptr<f8E8M0FNU>> -> tile<32x2xptr<f8E8M0FNU>>
    %50 = offset %49, %47 : tile<32x2xptr<f8E8M0FNU>>, tile<32x2xi32> -> tile<32x2xptr<f8E8M0FNU>>
    %51, %52 = load_ptr_tko weak %50 token=%35 : tile<32x2xptr<f8E8M0FNU>> -> tile<32x2xf8E8M0FNU>, token
    %53 = reshape %1 : tile<i32> -> tile<1x1xi32>
    %54 = broadcast %53 : tile<1x1xi32> -> tile<2x32xi32>
    %55 = iota : tile<2xi32>
    %56 = reshape %55 : tile<2xi32> -> tile<2x1xi32>
    %57 = broadcast %56 : tile<2x1xi32> -> tile<2x32xi32>
    %58 = constant <i32: 32> : tile<2x32xi32>
    %59 = muli %57, %58 : tile<2x32xi32>
    %60 = addi %54, %59 : tile<2x32xi32>
    %61 = iota : tile<32xi32>
    %62 = reshape %61 : tile<32xi32> -> tile<1x32xi32>
    %63 = broadcast %62 : tile<1x32xi32> -> tile<2x32xi32>
    %64 = addi %60, %63 : tile<2x32xi32>
    %65 = reshape %arg3 : tile<ptr<f8E8M0FNU>> -> tile<1x1xptr<f8E8M0FNU>>
    %66 = broadcast %65 : tile<1x1xptr<f8E8M0FNU>> -> tile<2x32xptr<f8E8M0FNU>>
    %67 = offset %66, %64 : tile<2x32xptr<f8E8M0FNU>>, tile<2x32xi32> -> tile<2x32xptr<f8E8M0FNU>>
    %68, %69 = load_ptr_tko weak %67 token=%52 : tile<2x32xptr<f8E8M0FNU>> -> tile<2x32xf8E8M0FNU>, token
    %70 = constant <f32: 0.0> : tile<32x32xf32>
    %71 = mmaf_scaled %17, %34, %70, %51, %68 : tile<32x64xf8E4M3FN>, tile<64x32xf8E4M3FN>, tile<32x32xf32>, tile<32x2xf8E8M0FNU>, tile<2x32xf8E8M0FNU>
    %72 = ftof %71 rounding<nearest_even> : tile<32x32xf32> -> tile<32x32xf64>
    %73 = reshape %1 : tile<i32> -> tile<1x1xi32>
    %74 = broadcast %73 : tile<1x1xi32> -> tile<32x32xi32>
    %75 = iota : tile<32xi32>
    %76 = reshape %75 : tile<32xi32> -> tile<32x1xi32>
    %77 = broadcast %76 : tile<32x1xi32> -> tile<32x32xi32>
    %78 = constant <i32: 32> : tile<32x32xi32>
    %79 = muli %77, %78 : tile<32x32xi32>
    %80 = addi %74, %79 : tile<32x32xi32>
    %81 = iota : tile<32xi32>
    %82 = reshape %81 : tile<32xi32> -> tile<1x32xi32>
    %83 = broadcast %82 : tile<1x32xi32> -> tile<32x32xi32>
    %84 = addi %80, %83 : tile<32x32xi32>
    %85 = reshape %arg4 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %86 = broadcast %85 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %87 = offset %86, %84 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %88 = store_ptr_tko weak %87, %72 token=%69 : tile<32x32xptr<f64>>, tile<32x32xf64> -> token
    return
  }
}
